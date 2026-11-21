from collections import defaultdict
from dataclasses import asdict, dataclass
import json


PUBLIC_DISPOSITIONS = ('release', 'retest')


@dataclass(frozen=True, slots=True)
class PublicEvidence:
    forced_retest: tuple[str, ...]
    forced_release: tuple[str, ...]
    implications: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AnalysisArtifact:
    version: int
    analysis_id: str
    batch_id: str
    revision_id: str
    policy_version: str
    minimum_work: int
    public_segments: tuple[str, ...]
    evidence: PublicEvidence


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f'duplicate artifact field {name}')
        result[name] = value
    return result


def _check_fields(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or value.keys() != expected:
        raise ValueError(f'invalid {label} fields')


def _identifier(value) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError('invalid artifact identifier')
    return value


def _ids(values) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise ValueError('expected an identifier list')
    ids = tuple(_identifier(value) for value in values)
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate identifier in artifact list')
    return ids


def _check_evidence_consistency(evidence: PublicEvidence) -> None:
    outgoing = defaultdict(list)
    for start, end in evidence.implications:
        outgoing[start].append(end)
    forced = set(evidence.forced_retest)
    pending = list(evidence.forced_retest)
    while pending:
        node = pending.pop()
        for target in outgoing[node]:
            if target not in forced:
                forced.add(target)
                pending.append(target)
    if forced.intersection(evidence.forced_release):
        raise ValueError('contradictory public evidence')


def _decode_evidence(value, public_segments: tuple[str, ...]) -> PublicEvidence:
    _check_fields(value, {'forced_retest', 'forced_release', 'implications'}, 'public evidence')
    order = {segment_id: index for index, segment_id in enumerate(public_segments)}
    retest = _ids(value['forced_retest'])
    release = _ids(value['forced_release'])
    if any(segment_id not in order for segment_id in retest + release):
        raise ValueError('forced disposition references a nonpublic segment')

    raw_links = value['implications']
    if not isinstance(raw_links, list):
        raise ValueError('expected an implication list')
    links = set()
    for raw in raw_links:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError('expected an implication pair')
        start, end = (_identifier(part) for part in raw)
        if start not in order or end not in order:
            raise ValueError('implication references a nonpublic segment')
        if (start, end) in links:
            raise ValueError('duplicate implication')
        links.add((start, end))

    evidence = PublicEvidence(
        tuple(sorted(retest, key=order.__getitem__)),
        tuple(sorted(release, key=order.__getitem__)),
        tuple(sorted(links, key=lambda pair: (order[pair[0]], order[pair[1]]))),
    )
    _check_evidence_consistency(evidence)
    return evidence


def encode_artifact(artifact: AnalysisArtifact) -> str:
    return json.dumps(asdict(artifact), sort_keys=True, separators=(',', ':'))


def decode_artifact(encoded: str) -> AnalysisArtifact:
    if type(encoded) is not str:
        raise ValueError('analysis artifact must be JSON text')
    payload = json.loads(encoded, object_pairs_hook=_unique_object)
    _check_fields(payload, {
        'version', 'analysis_id', 'batch_id', 'revision_id', 'policy_version',
        'minimum_work', 'public_segments', 'evidence',
    }, 'analysis artifact')
    if type(payload['version']) is not int or payload['version'] != 1:
        raise ValueError('unsupported analysis version')
    minimum_work = payload['minimum_work']
    if type(minimum_work) is not int or minimum_work < 0:
        raise ValueError('invalid minimum work')
    public_segments = _ids(payload['public_segments'])
    return AnalysisArtifact(
        version=1,
        analysis_id=_identifier(payload['analysis_id']),
        batch_id=_identifier(payload['batch_id']),
        revision_id=_identifier(payload['revision_id']),
        policy_version=_identifier(payload['policy_version']),
        minimum_work=minimum_work,
        public_segments=public_segments,
        evidence=_decode_evidence(payload['evidence'], public_segments),
    )
