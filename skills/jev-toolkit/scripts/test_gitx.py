import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import gitx

KEY_PRESENT = Path("~/.typesafe_key").expanduser().is_file() or bool(os.environ.get("TYPESAFE_API_KEY"))


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write(repo, name, text):
    path = Path(repo, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class RepoCase(unittest.TestCase):
    """A working clone on branch `work`, with a bare origin whose default branch is main."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.origin, self.work = base / "origin.git", base / "work"
        sh(base, "init", "--bare", "-b", "main", str(self.origin))
        self.work.mkdir()
        sh(self.work, "init", "-b", "main")
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            sh(self.work, "config", key, value)
        sh(self.work, "remote", "add", "origin", str(self.origin))
        write(self.work, "README.md", "hello wrold\n")
        write(self.work, "config.ini", "debug = false\n")
        write(self.work, "app.py", "def total(items):\n    return sum(items)\n")
        sh(self.work, "add", ".")
        sh(self.work, "commit", "-m", "init")
        sh(self.work, "push", "origin", "main")
        sh(self.work, "remote", "set-head", "origin", "main")
        sh(self.work, "checkout", "-b", "work")
        self.log = base / "log.jsonl"
        self.repo = gitx.Repo(self.work, log_path=self.log)

    def tearDown(self):
        self.tmp.cleanup()

    def commit_file(self, name, text, message="change"):
        write(self.work, name, text)
        sh(self.work, "add", name)
        sh(self.work, "commit", "-m", message)

    def logged(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]


class Run(RepoCase):
    def test_failed_git_command_raises_with_command_and_stderr(self):
        with self.assertRaises(gitx.GitError) as caught:
            gitx.run(["checkout", "no-such-branch"], cwd=self.work)
        self.assertIn("checkout", " ".join(caught.exception.command))
        self.assertTrue(caught.exception.stderr)
        self.assertNotEqual(caught.exception.returncode, 0)

    def test_failure_stops_the_chain(self):
        with self.assertRaises(gitx.GitError):
            self.repo.commit(["missing.txt"], "nope")
        self.assertEqual(self.logged()[-1]["result"].split(":")[0], "GitError")


class Commit(RepoCase):
    def test_commit_passes_and_logs_ok(self):
        write(self.work, "README.md", "hello world\n")
        record = self.repo.commit(["README.md"], "fix typo")
        self.assertEqual(record["result"], "ok")
        self.assertEqual(self.logged()[-1]["op"], "commit")
        self.assertEqual(sh(self.work, "show", "--name-only", "--format=", "HEAD"), "README.md")

    def test_contract_catches_an_extra_staged_file(self):
        write(self.work, "README.md", "hello world\n")
        write(self.work, "config.ini", "debug = true\n")
        sh(self.work, "add", "config.ini")
        with self.assertRaises(gitx.ContractError) as caught:
            self.repo.commit(["README.md"], "fix typo")
        self.assertIn("config.ini", str(caught.exception))
        self.assertTrue(self.logged()[-1]["result"].startswith("ContractError"))

    def test_verify_commit_catches_a_commit_with_extra_files(self):
        before = self.repo.head()
        write(self.work, "README.md", "hello world\n")
        write(self.work, "config.ini", "debug = true\n")
        sh(self.work, "commit", "-a", "-m", "both")
        with self.assertRaises(gitx.ContractError):
            self.repo.verify_commit(["README.md"], before)

    def test_directory_paths_cover_their_files(self):
        write(self.work, "pkg/a.py", "a = 1\n")
        write(self.work, "pkg/b.py", "b = 2\n")
        self.assertEqual(self.repo.commit(["pkg"], "add pkg")["result"], "ok")

    def test_paths_resolve_from_a_subdirectory(self):
        write(self.work, "sub/x.txt", "x\n")
        repo = gitx.Repo(self.work / "sub", log_path=self.log)
        self.assertEqual(repo.commit(["x.txt"], "add x")["result"], "ok")


class Revert(RepoCase):
    def test_revert_passes(self):
        self.commit_file("config.ini", "debug = true\n")
        target = self.repo.head()
        self.assertEqual(self.repo.revert(target)["result"], "ok")
        self.assertEqual(Path(self.work, "config.ini").read_text(), "debug = false\n")

    def test_contract_catches_a_non_inverse_commit(self):
        self.commit_file("config.ini", "debug = true\n")
        target, before = self.repo.head(), self.repo.head()
        self.commit_file("config.ini", "debug = maybe\n", "not an inverse")
        with self.assertRaises(gitx.ContractError):
            self.repo.verify_revert(target, before)

    def test_conflicting_revert_raises_and_leaves_no_revert_in_progress(self):
        self.commit_file("config.ini", "debug = true\n")
        target = self.repo.head()
        self.commit_file("config.ini", "debug = other\n")
        with self.assertRaises(gitx.GitError):
            self.repo.revert(target)
        self.assertFalse(Path(self.work, ".git", "REVERT_HEAD").exists())


class Push(RepoCase):
    def test_push_passes_against_a_real_origin_and_sets_upstream(self):
        self.commit_file("config.ini", "debug = true\n")
        self.assertEqual(self.repo.push()["result"], "ok")
        self.assertEqual(sh(self.origin, "rev-parse", "refs/heads/work"), self.repo.head())
        self.assertEqual(sh(self.work, "rev-parse", "--abbrev-ref", "work@{upstream}"), "origin/work")
        self.assertEqual(sh(self.work, "rev-parse", "refs/remotes/origin/work"), self.repo.head())

    def test_contract_catches_a_local_ahead_state(self):
        self.repo.push()
        self.commit_file("config.ini", "debug = true\n")
        with self.assertRaises(gitx.ContractError) as caught:
            self.repo.verify_push("work")
        self.assertIn("refs/heads/work", str(caught.exception))

    def test_push_refreshes_a_stale_tracking_ref(self):
        self.commit_file("config.ini", "debug = true\n")
        self.repo.push()
        sh(self.work, "update-ref", "refs/remotes/origin/work", sh(self.work, "rev-parse", "main"))  # the false alarm
        self.assertEqual(self.repo.push()["result"], "ok")
        self.assertEqual(sh(self.work, "rev-parse", "refs/remotes/origin/work"), self.repo.head())

    def test_push_works_from_a_shallow_clone(self):
        clone = Path(self.tmp.name, "shallow")
        sh(self.tmp.name, "clone", "--depth", "1", f"file://{self.origin}", str(clone))
        for key, value in (("user.name", "t"), ("user.email", "t@example.com"), ("commit.gpgsign", "false")):
            sh(clone, "config", key, value)
        sh(clone, "checkout", "-b", "feature")
        write(clone, "new.txt", "new\n")
        repo = gitx.Repo(clone, log_path=self.log)
        repo.commit(["new.txt"], "add new")
        self.assertEqual(repo.push()["result"], "ok")


class BranchGuard(RepoCase):
    def test_commit_and_push_refuse_the_default_branch(self):
        sh(self.work, "checkout", "main")
        write(self.work, "README.md", "hello world\n")
        with self.assertRaises(gitx.BranchGuardError):
            self.repo.commit(["README.md"], "fix")
        with self.assertRaises(gitx.BranchGuardError):
            self.repo.push()
        self.assertEqual(sh(self.work, "log", "--format=%s").split("\n"), ["init"])

    def test_allow_default_overrides(self):
        sh(self.work, "checkout", "main")
        write(self.work, "README.md", "hello world\n")
        self.assertEqual(self.repo.commit(["README.md"], "fix", allow_default=True)["result"], "ok")

    def test_default_falls_back_to_main_or_master_without_origin_head(self):
        sh(self.work, "remote", "set-head", "origin", "--delete")
        self.assertEqual(self.repo.default_branch(), "main")
        sh(self.work, "branch", "-m", "main", "master")
        self.assertEqual(self.repo.default_branch(), "master")


class IntentGate(RepoCase):
    def fake_ask(self, score):
        return lambda state, questions: {"answers": {"match": {"score": score}}}

    def test_judge_intent_bands(self):
        gitx.judge_intent(2.7)
        for score, word in ((2.5, "doubtful"), (1.0, "below threshold")):
            with self.assertRaises(gitx.IntentError) as caught:
                gitx.judge_intent(score)
            self.assertIn(word, str(caught.exception))

    def test_low_score_blocks_the_commit_and_unstages(self):
        repo = gitx.Repo(self.work, ask=self.fake_ask(0.5), log_path=self.log)
        write(self.work, "README.md", "hello world\n")
        head = repo.head()
        with self.assertRaises(gitx.IntentError):
            repo.commit(["README.md"], "fix", intent="fix the typo")
        self.assertEqual(repo.head(), head)
        self.assertEqual(repo.staged_files(), set())
        self.assertEqual(self.logged()[-1]["intent_score"], 0.5)

    def test_high_score_lets_the_commit_through_and_is_logged(self):
        repo = gitx.Repo(self.work, ask=self.fake_ask(2.9), log_path=self.log)
        write(self.work, "README.md", "hello world\n")
        record = repo.commit(["README.md"], "fix", intent="fix the typo")
        self.assertEqual((record["result"], record["intent_score"]), ("ok", 2.9))


@unittest.skipUnless(KEY_PRESENT, "no TypeSafe key")
class NegativeControls(RepoCase):
    """Live Jev calls. Same intent, three diffs; scores are printed, assertions only demand an ordering."""

    INTENT = "fix the typo in README"
    scores: dict = {}

    def diff_of(self, edits):
        for name, text in edits.items():
            write(self.work, name, text)
        diff = sh(self.work, "diff")
        sh(self.work, "checkout", ".")
        return diff

    def test_scores(self):
        cases = {
            "a_fix_only": {"README.md": "hello world\n"},
            "b_fix_plus_unrelated_config": {"README.md": "hello world\n", "config.ini": "debug = true\nverbose = true\n"},
            "c_unrelated_function_rewrite": {"app.py": "def total(items):\n    result = 0\n    for item in items:\n"
                                                     "        result += item * item\n    return result\n"},
        }
        scores = {name: gitx.check_intent(self.INTENT, self.diff_of(edits)) for name, edits in cases.items()}
        print("\nNEGATIVE CONTROL SCORES (0-3):", json.dumps(scores))
        self.assertGreaterEqual(scores["a_fix_only"], 2.5)
        self.assertLess(scores["b_fix_plus_unrelated_config"], scores["a_fix_only"])
        self.assertLess(scores["c_unrelated_function_rewrite"], scores["a_fix_only"])


if __name__ == "__main__":
    unittest.main()
