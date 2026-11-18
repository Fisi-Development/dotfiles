"""Size limits for the always-loaded instruction files this repository deploys.

Royal set the limits on 7 Nov 2026 (Harbor backlog 2026-11-07-injected-context-budget):
20 KB for the shared agreement, 17 KB for the authorization policy (raised from 15 KB
the same day, once Claude sessions stopped importing it) and 16 KB for a repository
AGENTS.md. KB is 1,000 bytes. Harbor's tools/context_budget.py checks the deployed
files and the fleet memory digest with the same limits (config/context-budget.json).

The agreement is stored age-encrypted. Its plaintext length follows from the age
framing alone (header, 16-byte nonce, 64 KiB chunks each with a 16-byte tag), so the
check needs no key.

The authorization policy also keeps headroom: the check fails once it is within
HEADROOM bytes of its limit, so the next rule never has to displace another one.
Royal's rule (18 Nov 2026): an addition that does not fit is made by moving
explanation to authorization-policy-notes.md, never by cutting a rule.
"""
import base64
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
CHUNK = 64 * 1024
TAG = 16
NONCE = 16

LIMITS = [
    ('shared agreement', 'home/encrypted_AGENTS.md.age', 20000),
    ('authorization policy', 'home/dot_agents/authorization-policy.md', 17000),
    ('repository AGENTS.md', 'AGENTS.md', 16000),
]
POLICY = 'home/dot_agents/authorization-policy.md'
HEADROOM = 500


def age_plaintext_size(data):
    """Plaintext length of an age v1 file, armored or binary, read from its framing."""
    if data.lstrip().startswith(b'-----BEGIN AGE ENCRYPTED FILE-----'):
        body = data.strip().splitlines()[1:-1]
        data = base64.b64decode(b''.join(line.strip() for line in body))
    if not data.startswith(b'age-encryption.org/v1\n'):
        raise ValueError('not an age v1 file')
    end = data.index(b'\n---')
    payload = len(data) - (data.index(b'\n', end + 1) + 1) - NONCE
    chunks = max(1, -(-payload // (CHUNK + TAG)))
    size = payload - chunks * TAG
    if size < 0:
        raise ValueError('truncated age payload')
    return size


def measure(path):
    data = path.read_bytes()
    return age_plaintext_size(data) if path.suffix == '.age' else len(data)


def over_limit(limits=LIMITS, root=ROOT):
    return [f'{name}: {rel} is {measure(root / rel):,} bytes, over the {limit:,}-byte limit'
            for name, rel, limit in limits if measure(root / rel) > limit]


def short_of_headroom(limits=LIMITS, root=ROOT, rel=POLICY, headroom=HEADROOM):
    limit = next(limit for _, path, limit in limits if path == rel)
    size = measure(root / rel)
    if size <= limit - headroom:
        return None
    return (f'{rel} is {size:,} bytes, within {headroom} of its {limit:,}-byte limit: '
            'move explanation to the notes file; do not cut a rule')


def fake_age(plaintext_size, armored=True):
    header = b'age-encryption.org/v1\n-> X25519 c3RhbnphCg\nYm9keQ\n--- bWFj\n'
    chunks = max(1, -(-plaintext_size // CHUNK))
    data = header + b'n' * NONCE + b'c' * (plaintext_size + chunks * TAG)
    if not armored:
        return data
    encoded = base64.b64encode(data)
    lines = [encoded[i:i + 64] for i in range(0, len(encoded), 64)]
    return b'\n'.join([b'-----BEGIN AGE ENCRYPTED FILE-----', *lines, b'-----END AGE ENCRYPTED FILE-----']) + b'\n'


class ContextBudgetTests(unittest.TestCase):
    def test_always_loaded_files_are_within_their_limits(self):
        self.assertEqual(over_limit(), [])

    def test_authorization_policy_keeps_headroom(self):
        self.assertIsNone(short_of_headroom())

    def test_headroom_check_fails_near_the_limit(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            limits = [('policy', 'p.md', 1000)]
            (root / 'p.md').write_text('x' * 500)
            self.assertIsNone(short_of_headroom(limits, root, 'p.md', 500))
            (root / 'p.md').write_text('x' * 501)
            found = short_of_headroom(limits, root, 'p.md', 500)
        self.assertEqual(found, 'p.md is 501 bytes, within 500 of its 1,000-byte limit: '
                                'move explanation to the notes file; do not cut a rule')

    def test_age_size_follows_the_framing(self):
        for size in (0, 1, 26658, CHUNK, CHUNK + 1, 3 * CHUNK + 5):
            for armored in (True, False):
                self.assertEqual(age_plaintext_size(fake_age(size, armored)), size, (size, armored))

    def test_an_oversized_file_is_named_with_its_size(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            (root / 'big.age').write_bytes(fake_age(20001))
            (root / 'small.md').write_text('x' * 10)
            found = over_limit([('agreement', 'big.age', 20000), ('policy', 'small.md', 10)], root)
        self.assertEqual(found, ['agreement: big.age is 20,001 bytes, over the 20,000-byte limit'])


if __name__ == '__main__':
    unittest.main()
