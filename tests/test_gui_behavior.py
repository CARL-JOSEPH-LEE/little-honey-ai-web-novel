from __future__ import annotations

import unittest

from gui import _should_follow_progress_scroll


class ProgressScrollTests(unittest.TestCase):
    def test_follow_when_view_is_already_at_bottom(self) -> None:
        self.assertTrue(_should_follow_progress_scroll((0.75, 1.0)))
        self.assertTrue(_should_follow_progress_scroll((0.73, 0.985)))

    def test_do_not_follow_when_user_reads_older_text(self) -> None:
        self.assertFalse(_should_follow_progress_scroll((0.25, 0.70)))
        self.assertFalse(_should_follow_progress_scroll((0.0, 0.40)))


if __name__ == "__main__":
    unittest.main()
