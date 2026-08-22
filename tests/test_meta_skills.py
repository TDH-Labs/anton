import os
import tempfile
import unittest

from anton.meta_skills import (
    META_LEARNING, UPSKILL_FROM_EXPERIENCE, UPSKILL_FROM_RESEARCH, seed_meta_skills,
)

# These three skills are adapted from a personal methodology in a separate,
# unrelated agent environment (see meta_skills.py's module docstring).
# Every install of Anton ships these to a different business -- if any of
# these substrings ever reappear, that personal infrastructure has leaked
# back in.
FORBIDDEN_SUBSTRINGS = (
    "second-brain",
    "harbor skill-install",
    "harbor sync",
    "~/rooms",
    "room_scope",
    "youtube-content",
    "anton-autonomous",
)

ALL_META_SKILLS = (UPSKILL_FROM_RESEARCH, UPSKILL_FROM_EXPERIENCE, META_LEARNING)


class TestMetaSkillsNoPersonalLeakage(unittest.TestCase):
    def test_no_meta_skill_has_personal_references(self):
        for text in ALL_META_SKILLS:
            for s in FORBIDDEN_SUBSTRINGS:
                self.assertNotIn(s, text, f"leaked personal reference: {s!r}")

    def test_research_and_experience_skills_reference_anton_native_equivalents(self):
        for text in (UPSKILL_FROM_RESEARCH, UPSKILL_FROM_EXPERIENCE):
            self.assertIn("data_dir", text)
            self.assertIn("vault/notes/research", text)

    def test_meta_learning_names_both_other_skills_as_the_paths_it_routes_to(self):
        self.assertIn("upskill-from-research", META_LEARNING)
        self.assertIn("upskill-from-experience", META_LEARNING)


class TestSeedMetaSkills(unittest.TestCase):
    def test_writes_all_three_skills(self):
        with tempfile.TemporaryDirectory() as data_dir:
            written = seed_meta_skills(data_dir)
            self.assertEqual(set(written),
                             {"upskill-from-research", "upskill-from-experience", "meta-learning"})
            for slug in written:
                self.assertTrue(os.path.exists(
                    os.path.join(data_dir, "skills", slug, "SKILL.md")))

    def test_idempotent_does_not_clobber_existing_edits(self):
        with tempfile.TemporaryDirectory() as data_dir:
            seed_meta_skills(data_dir)
            path = os.path.join(data_dir, "skills", "upskill-from-research", "SKILL.md")
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n## Local addition\n")
            seed_meta_skills(data_dir)
            with open(path, encoding="utf-8") as f:
                self.assertIn("Local addition", f.read())

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory() as data_dir:
            seed_meta_skills(data_dir)
            path = os.path.join(data_dir, "skills", "upskill-from-research", "SKILL.md")
            with open(path, "a", encoding="utf-8") as f:
                f.write("\n## Local addition\n")
            seed_meta_skills(data_dir, force=True)
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("Local addition", f.read())


if __name__ == "__main__":
    unittest.main()
