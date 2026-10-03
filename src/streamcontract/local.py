"""Single-writer local commits: immutable generations plus one visibility pointer.

Unkeyed hashes detect mismatches, not hostile replacement. This is a local file
protocol, not a transaction with an external consumer or a broker.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import uuid

from .contract import Contract, canonical, strict_json
from .engine import CheckpointError, Engine, ResourceLimit

META_LIMIT = 65536
RECORD_LIMIT = 262144
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_STORE = re.compile(r"[0-9a-f]{32}\Z")
_GEN = re.compile(r"g([1-9][0-9]{0,18})-([0-9a-f]{32})\Z")


def _transition_hook(stage: str) -> None:
    """Private no-op seam for real process interruption tests."""


def _error(message="invalid local commit"):
    raise CheckpointError(message)


def _hash(value):
    return type(value) is str and _HASH.fullmatch(value) is not None


def _int(value, minimum=0):
    return type(value) is int and minimum <= value <= 2**63 - 1


def _json(raw):
    try:
        # The new file protocol requires UTF-8, without a BOM (legacy unchanged).
        if raw.startswith(b"\xef\xbb\xbf"):
            _error("local JSON BOM is forbidden")
        value = strict_json(raw.decode("utf-8"))
        canonical(value)  # rejects overflow-to-infinity and lone surrogates too
        return value
    except (UnicodeError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, CheckpointError):
            raise
        raise CheckpointError("invalid local JSON encoding") from exc


def _file(root, name):
    path = root / name
    if path.is_symlink() or not path.is_file():
        _error("local commit file missing or not regular")
    return path


def _read(root, name, cap):
    with _file(root, name).open("rb") as file:
        raw = file.read(cap + 1)
    if len(raw) > cap:
        _error("local metadata exceeds limit")
    return raw


def _identity(root, contract):
    if root.is_symlink() or not root.is_dir():
        _error("local output directory must be a regular directory")
    identity = _json(_read(root, "IDENTITY.json", META_LIMIT))
    if (type(identity) is not dict or set(identity) != {"version", "store_id", "contract_sha256"}
            or type(identity["version"]) is not int or identity["version"] != 1
            or type(identity["store_id"]) is not str or not _STORE.fullmatch(identity["store_id"])
            or identity["contract_sha256"] != contract.digest):
        _error("local output identity or contract mismatch")
    return identity["store_id"]


def _write(path, raw):
    # Create-only: even an orphan from an interrupted commit is never overwritten.
    with path.open("xb") as file:
        file.write(raw)
        file.flush()
        os.fsync(file.fileno())


def _directory_sync(root):
    # Windows does not expose a portable directory fsync. Visibility remains
    # atomic; hardware/power-loss durability is explicitly not guaranteed.
    if os.name != "nt":
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


@contextmanager
def _writer(root, contract):
    if root.is_symlink():
        _error("local output directory must not be a symlink")
    if not root.exists():
        root.mkdir(parents=True)
        _write(root / "IDENTITY.json", canonical({"version": 1, "store_id": uuid.uuid4().hex,
                                                 "contract_sha256": contract.digest}))
        _write(root / "LOCK", b"0")
        _directory_sync(root)
    store = _identity(root, contract)  # existing unrelated directories are rejected
    lock = _file(root, "LOCK")
    with lock.open("r+b") as file:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CheckpointError("local output writer already active") from exc
        try:
            yield store
        finally:
            if os.name == "nt":
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def _ref(value):
    if (type(value) is not dict or set(value) != {"name", "sha256"}
            or type(value["name"]) is not str or not _GEN.fullmatch(value["name"])
            or not _hash(value["sha256"])):
        _error("invalid generation reference")


def _chain(root, contract, store):
    """Capture one pointer, validate every immutable ancestor, restore latest v3."""
    if not (root / "CURRENT.json").exists():
        return [], Engine(contract), None
    pointer = _json(_read(root, "CURRENT.json", META_LIMIT))
    if (type(pointer) is not dict or set(pointer) != {"version", "store_id", "commit"}
            or type(pointer["version"]) is not int or pointer["version"] != 1
            or pointer["store_id"] != store):
        _error("invalid local commit pointer")
    reference = pointer["commit"]
    chain, seen = [], set()
    while reference is not None:
        _ref(reference)
        name = reference["name"]
        if name in seen:
            _error("cyclic local commit chain")
        seen.add(name)
        raw = _read(root, name + ".manifest.json", META_LIMIT)
        if hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            _error("local manifest digest mismatch")
        manifest = _json(raw)
        required = {"version", "store_id", "generation", "parent", "contract_sha256", "source",
                    "checkpoint_sha256", "checkpoint_bytes", "output_sha256", "output_bytes",
                    "output_count", "total_outputs", "phase", "summary", "exit_code"}
        if (type(manifest) is not dict or set(manifest) != required
                or type(manifest["version"]) is not int or manifest["version"] != 1
                or manifest["store_id"] != store or manifest["contract_sha256"] != contract.digest
                or not _int(manifest["generation"], 1)
                or manifest["generation"] != int(_GEN.fullmatch(name)[1])
                or not _hash(manifest["checkpoint_sha256"]) or not _hash(manifest["output_sha256"])
                or not _int(manifest["checkpoint_bytes"], 1) or not _int(manifest["output_bytes"])
                or not _int(manifest["output_count"]) or not _int(manifest["total_outputs"])
                or type(manifest["phase"]) is not str or manifest["phase"] not in {"paused", "finished", "resource_stop"}
                or type(manifest["exit_code"]) is not int or manifest["exit_code"] not in {0, 2, 3}
                or type(manifest["summary"]) is not dict):
            _error("invalid local manifest schema")
        source = manifest["source"]
        if (type(source) is not dict or set(source) != {"lines", "prefix_sha256"}
                or not _int(source["lines"]) or not _hash(source["prefix_sha256"])):
            _error("invalid local source position")
        checkpoint = _read(root, name + ".checkpoint.json", contract.limits["max_checkpoint_bytes"])
        if len(checkpoint) != manifest["checkpoint_bytes"] or hashlib.sha256(checkpoint).hexdigest() != manifest["checkpoint_sha256"]:
            _error("local checkpoint digest mismatch")
        _binding(checkpoint, manifest, contract)
        chain.append((name, manifest, reference, checkpoint if not chain else None))
        reference = manifest["parent"]
    chain.reverse()
    previous_lines = previous_outputs = 0
    for ordinal, (_, manifest, _, _) in enumerate(chain, 1):
        if (manifest["generation"] != ordinal or manifest["source"]["lines"] < previous_lines
                or manifest["total_outputs"] != previous_outputs + manifest["output_count"]
                or (ordinal < len(chain) and manifest["phase"] != "paused")):
            _error("inconsistent local commit chain")
        previous_lines, previous_outputs = manifest["source"]["lines"], manifest["total_outputs"]
    latest = chain[-1]
    engine, source = Engine.restore(contract, latest[3])
    if (canonical(source) != canonical(latest[1]["source"])
            or canonical(engine.summary()) != canonical(latest[1]["summary"])
            or engine.finished != (latest[1]["phase"] == "finished")
            or latest[1]["exit_code"] != (3 if latest[1]["phase"] == "resource_stop" else
                                          2 if engine.summary()["status"] in {"EMPTY", "ISSUES"} else 0)):
        _error("local checkpoint and manifest state mismatch")
    return chain, engine, source


def _binding(raw, manifest, contract):
    """Bind every historic snapshot's envelope/source/summary; restore latest fully."""
    document = _json(raw)
    if type(document) is not dict or set(document) != {"payload", "sha256"}:
        _error("invalid local checkpoint envelope")
    payload = document["payload"]
    expected = {"version", "contract_sha256", "sequence", "max_event_time", "watermark",
                "stats", "finished", "windows", "source"}
    if (type(payload) is not dict or set(payload) != expected or type(payload["version"]) is not int
            or payload["version"] != 3 or payload["contract_sha256"] != contract.digest
            or document["sha256"] != hashlib.sha256(canonical(payload)).hexdigest()
            or not _int(payload["sequence"]) or type(payload["finished"]) is not bool
            or canonical(payload["source"]) != canonical(manifest["source"])
            or payload["sequence"] != manifest["source"]["lines"]
            or type(payload["stats"]) is not dict or set(payload["stats"]) != set(Engine(contract).stats)
            or any(not _int(v) for v in payload["stats"].values())
            or type(payload["windows"]) is not list
            or any(type(w) is not dict or type(w.get("groups")) is not list for w in payload["windows"])
            or (payload["watermark"] is not None and type(payload["watermark"]) is not int)):
        _error("local checkpoint metadata mismatch")
    stats = payload["stats"]
    issues = stats["invalid"] + stats["late"] + stats["failed"] + stats["insufficient"]
    status = "EMPTY" if payload["sequence"] == 0 else "ISSUES" if issues else "COMPLETE" if payload["finished"] else "PAUSED"
    summary = {"kind": "summary", "status": status,
               "action": "investigate" if status == "EMPTY" else "quarantine" if issues else "release" if payload["finished"] else "resume",
               "sequence": payload["sequence"], "contract_sha256": contract.digest, "watermark_ms": payload["watermark"],
               "stats": stats, "active_windows": len(payload["windows"]),
               "active_groups": sum(len(w["groups"]) for w in payload["windows"]), "finished": payload["finished"]}
    if (canonical(summary) != canonical(manifest["summary"])
            or payload["finished"] != (manifest["phase"] == "finished")
            or manifest["exit_code"] != (3 if manifest["phase"] == "resource_stop" else 2 if status in {"EMPTY", "ISSUES"} else 0)):
        _error("local summary metadata mismatch")


def _output_id(store, index, decision):
    return hashlib.sha256(canonical([store, index, decision])).hexdigest()


def _rows(root, chain, store):
    index = sequence = 0
    for name, manifest, _, _ in chain:
        digest, size, count = hashlib.sha256(), 0, 0
        terminal = stopped = False
        with _file(root, name + ".outputs.jsonl").open("rb") as file:
            while raw := file.readline(RECORD_LIMIT + 1):
                if len(raw) > RECORD_LIMIT or not raw.endswith(b"\n"):
                    _error("local output record limit or truncation")
                row = _json(raw)
                if (type(row) is not dict or set(row) != {"version", "index", "output_id", "decision"}
                        or type(row["version"]) is not int or row["version"] != 1
                        or type(row["index"]) is not int or row["index"] != index + 1
                        or type(row["decision"]) is not dict or not _hash(row["output_id"])
                        or row["output_id"] != _output_id(store, row["index"], row["decision"])
                        or raw != canonical(row) + b"\n" or terminal):
                    _error("invalid local output identity or encoding")
                decision = row["decision"]
                kind = decision.get("kind")
                if kind == "event":
                    if stopped or type(decision.get("sequence")) is not int or decision["sequence"] != sequence + 1:
                        _error("local event sequence mismatch")
                    sequence += 1
                elif kind == "window":
                    if stopped or type(decision.get("sequence")) is not int or decision["sequence"] != sequence:
                        _error("local window sequence mismatch")
                elif kind == "error":
                    if (stopped or manifest["phase"] != "resource_stop" or decision.get("consumed") is not False
                            or type(decision.get("next_sequence")) is not int or decision["next_sequence"] != sequence + 1):
                        _error("invalid local stop decision")
                    stopped = True
                elif kind == "summary":
                    if (manifest["phase"] == "paused" or stopped != (manifest["phase"] == "resource_stop")
                            or canonical(decision) != canonical(manifest["summary"])):
                        _error("invalid local terminal summary")
                    terminal = True
                else:
                    _error("invalid local decision kind")
                index += 1
                count += 1
                size += len(raw)
                digest.update(raw)
                yield row
        if (count != manifest["output_count"] or index != manifest["total_outputs"]
                or size != manifest["output_bytes"] or digest.hexdigest() != manifest["output_sha256"]
                or sequence != manifest["source"]["lines"]
                or terminal != (manifest["phase"] != "paused")):
            _error("local output generation digest or count mismatch")


def _prefix(file, contract, source):
    from .cli import records
    iterator, digest = iter(records(file, contract.limits["max_event_bytes"])), hashlib.sha256()
    if source:
        for _ in range(source["lines"]):
            try:
                _, digest = next(iterator)
            except StopIteration as exc:
                raise CheckpointError("source shorter than local commit prefix") from exc
        if digest.hexdigest() != source["prefix_sha256"]:
            _error("local source prefix mismatch")
    return iterator, digest


def read_committed(directory, contract: Contract, *, input_path=None, after_index=0):
    """Validate the captured complete history before yielding its bounded rows.

    ``after_index`` is a consumer cursor. A consumer must persist its cursor with
    its own side effects; this API supplies no external transaction. A trusted
    directory must remain immutable while reading. Checking source requires the
    original file; without input_path only the stored prefix binding is checked.
    """
    if not _int(after_index):
        _error("invalid consumer cursor")
    root = Path(directory)
    store = _identity(root, contract)
    chain, _, source = _chain(root, contract, store)
    if after_index > (chain[-1][1]["total_outputs"] if chain else 0):
        _error("consumer cursor exceeds committed output")
    if input_path is not None:
        with Path(input_path).open("rb") as file:
            _prefix(file, contract, source)
    for _ in _rows(root, chain, store):
        pass
    for row in _rows(root, chain, store):
        if row["index"] > after_index:
            yield row


class _Stage:
    def __init__(self, root, store, generation, start_index):
        self.root, self.store = root, store
        self.name = f"g{generation}-{uuid.uuid4().hex}"
        self.file = (root / (self.name + ".outputs.jsonl")).open("xb")
        self.digest = hashlib.sha256()
        self.bytes = self.count = 0
        self.index = start_index

    def append(self, decision):
        index = self.index + 1
        raw = canonical({"version": 1, "index": index,
                         "output_id": _output_id(self.store, index, decision), "decision": decision}) + b"\n"
        if len(raw) > RECORD_LIMIT:
            _error("local output record exceeds limit")
        self.file.write(raw)
        _transition_hook("stage_record_written")
        self.digest.update(raw)
        self.bytes += len(raw)
        self.count += 1
        self.index = index

    def commit(self, engine, source, parent, phase):
        checkpoint = engine.checkpoint(source)  # limit failure leaves pointer unchanged
        summary = engine.summary()
        exit_code = 3 if phase == "resource_stop" else 2 if summary["status"] in {"EMPTY", "ISSUES"} else 0
        self.file.flush()
        os.fsync(self.file.fileno())
        self.file.close()
        _transition_hook("output_fsynced")
        _write(self.root / (self.name + ".checkpoint.json"), checkpoint)
        _transition_hook("checkpoint_fsynced")
        manifest = {"version": 1, "store_id": self.store, "generation": int(_GEN.fullmatch(self.name)[1]),
                    "parent": parent, "contract_sha256": engine.contract.digest, "source": source,
                    "checkpoint_sha256": hashlib.sha256(checkpoint).hexdigest(), "checkpoint_bytes": len(checkpoint),
                    "output_sha256": self.digest.hexdigest(), "output_bytes": self.bytes,
                    "output_count": self.count, "total_outputs": self.index, "phase": phase,
                    "summary": summary, "exit_code": exit_code}
        raw = canonical(manifest)
        if len(raw) > META_LIMIT:
            _error("local manifest exceeds limit")
        _write(self.root / (self.name + ".manifest.json"), raw)
        _transition_hook("manifest_fsynced")
        reference = {"name": self.name, "sha256": hashlib.sha256(raw).hexdigest()}
        pointer = canonical({"version": 1, "store_id": self.store, "commit": reference})
        temporary = self.root / (self.name + ".pointer.tmp")
        _write(temporary, pointer)
        _transition_hook("before_publish")
        current = self.root / "CURRENT.json"
        if current.is_symlink():
            _error("local pointer must not be a symlink")
        os.replace(temporary, current)
        _transition_hook("after_publish")
        _directory_sync(self.root)
        _transition_hook("directory_fsynced")
        return reference, manifest

    def close(self):
        self.file.close()


def process_local(contract: Contract, input_path, directory, *, stop_after=None, commit_every=64):
    """Publish bounded local batches; reopening verifies and resumes their prefix.

    Pauses store progress in manifests. The decision stream receives one summary
    only at EOF/resource stop. A completed bundle remains completed even if the
    input subsequently grows. Use a new directory for a new run/contract.
    """
    if stop_after is not None and not _int(stop_after):
        _error("stop_after must be a nonnegative integer")
    if not _int(commit_every, 1) or commit_every > 1000000:
        _error("commit_every must be in 1..1000000")
    root = Path(directory)
    protected = Path(input_path).resolve()
    resolved_root = root.resolve()
    if protected == resolved_root or resolved_root in protected.parents:
        _error("input must be outside local output directory")
    with _writer(root, contract) as store:
        chain, engine, source = _chain(root, contract, store)
        for _ in _rows(root, chain, store):
            pass
        parent = chain[-1][2] if chain else None
        generation = len(chain) + 1
        index = chain[-1][1]["total_outputs"] if chain else 0
        stage = None
        try:
            with Path(input_path).open("rb") as file:
                iterator, digest = _prefix(file, contract, source)
                if chain and chain[-1][1]["phase"] != "paused":
                    return _receipt(store, chain[-1][1])
                if stop_after == 0 and chain:
                    return _receipt(store, chain[-1][1])
                consumed = batch = 0
                for raw, next_digest in iterator:
                    if stop_after is not None and consumed >= stop_after:
                        break
                    try:
                        if raw is None:
                            decisions = engine.reject("event_bytes_limit")
                        else:
                            try:
                                event = strict_json(raw)
                            except UnicodeDecodeError:
                                decisions = engine.reject("invalid_utf8")
                            except (ValueError, OverflowError, RecursionError):
                                decisions = engine.reject("invalid_json")
                            else:
                                decisions = engine.push(event)
                    except ResourceLimit as exc:
                        if stage is None:
                            stage = _Stage(root, store, generation, index)
                        stage.append({"kind": "error", "status": "RESOURCE_LIMIT", "action": "stop",
                                      "limit": exc.limit, "next_sequence": exc.sequence, "consumed": False})
                        stage.append(engine.summary())
                        _, manifest = stage.commit(engine, {"lines": engine.sequence, "prefix_sha256": digest.hexdigest()},
                                                   parent, "resource_stop")
                        return _receipt(store, manifest)
                    if stage is None:
                        stage = _Stage(root, store, generation, index)
                    for decision in decisions:
                        stage.append(decision)
                    digest = next_digest
                    consumed += 1
                    batch += 1
                    if batch == commit_every:
                        parent, manifest = stage.commit(engine, {"lines": engine.sequence, "prefix_sha256": digest.hexdigest()}, parent, "paused")
                        generation += 1
                        index = stage.index
                        stage = None
                        batch = 0
                if stop_after is None:
                    if stage is None:
                        stage = _Stage(root, store, generation, index)
                    for decision in engine.finish():
                        stage.append(decision)
                    stage.append(engine.summary())
                elif stage is None and consumed:
                    return _receipt(store, manifest)
                if stage is None:
                    stage = _Stage(root, store, generation, index)
                _, manifest = stage.commit(engine, {"lines": engine.sequence, "prefix_sha256": digest.hexdigest()},
                                           parent, "finished" if stop_after is None else "paused")
                return _receipt(store, manifest)
        finally:
            if stage is not None:
                stage.close()


def _receipt(store, manifest):
    return {"kind": "local_commit", "store_id": store, "generation": manifest["generation"],
            "phase": manifest["phase"], "total_outputs": manifest["total_outputs"],
            "summary": manifest["summary"], "exit_code": manifest["exit_code"]}
