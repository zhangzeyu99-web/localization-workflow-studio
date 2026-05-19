import json
import tempfile
import unittest
from pathlib import Path

from workspace_runner import (
    WorkspaceTask,
    discover_workspace_tasks,
    merge_term_files,
)


class WorkspaceRunnerTests(unittest.TestCase):
    def test_discovers_english_project_task_and_ignores_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "通用术语表英语.xlsx").write_text("common", encoding="utf-8")

            project = root / "土拨鼠"
            project.mkdir()
            (project / "~$土拨鼠英语整体校对.xlsx").write_text("tmp", encoding="utf-8")
            (project / "土拨鼠英语整体校对.xlsx").write_text("lang", encoding="utf-8")
            (project / "土拨鼠印尼语整体校对.xlsx").write_text("idn", encoding="utf-8")
            (project / "土拨鼠术语表英语_约束完整.xlsx").write_text("term", encoding="utf-8")
            (project / "土拨鼠术语表印尼_约束完整.xlsx").write_text("term-idn", encoding="utf-8")

            tasks = discover_workspace_tasks(root, lang="en")

            self.assertEqual(len(tasks), 1)
            task = tasks[0]
            self.assertEqual(task.project_name, "土拨鼠")
            self.assertEqual(task.language_file.name, "土拨鼠英语整体校对.xlsx")
            self.assertEqual(
                [path.name for path in task.term_files],
                ["通用术语表英语.xlsx", "土拨鼠术语表英语_约束完整.xlsx"],
            )

    def test_prefers_shallower_project_language_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "项目A"
            nested = project / "历史版本"
            nested.mkdir(parents=True)

            (project / "项目A英语整体校对.xlsx").write_text("new", encoding="utf-8")
            (nested / "项目A英语语言表.xlsx").write_text("old", encoding="utf-8")
            (project / "项目A术语表英语.xlsx").write_text("term", encoding="utf-8")

            tasks = discover_workspace_tasks(root, lang="en")

            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].language_file.parent, project)

    def test_merges_term_files_with_project_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = root / "common.json"
            project = root / "project.json"
            common.write_text(
                json.dumps({"通用术语": "Common Term", "冲突术语": "Common Value"}, ensure_ascii=False),
                encoding="utf-8",
            )
            project.write_text(
                json.dumps({"项目术语": "Project Term", "冲突术语": "Project Value"}, ensure_ascii=False),
                encoding="utf-8",
            )

            merged = merge_term_files([common, project])

            self.assertEqual(merged["通用术语"]["primary"], "Common Term")
            self.assertEqual(merged["项目术语"]["primary"], "Project Term")
            self.assertEqual(merged["冲突术语"]["primary"], "Project Value")

    def test_ignores_generic_folder_names_and_keeps_best_term_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "通用术语表英语.xlsx").write_text("common", encoding="utf-8")

            generic = root / "新建文件夹"
            generic.mkdir()
            (generic / "土拨鼠英语语言表_term_rewrite_only.xlsx").write_text("lang", encoding="utf-8")

            project = root / "土拨鼠"
            history = project / "新建文件夹"
            history.mkdir(parents=True)
            (project / "土拨鼠英语整体校对.xlsx").write_text("lang", encoding="utf-8")
            (history / "土拨鼠术语表英语.xlsx").write_text("old-term", encoding="utf-8")
            (project / "土拨鼠术语表英语_约束完整.xlsx").write_text("best-term", encoding="utf-8")

            tasks = discover_workspace_tasks(root, lang="en")

            self.assertEqual([task.project_name for task in tasks], ["土拨鼠"])
            self.assertEqual(
                [path.name for path in tasks[0].term_files],
                ["通用术语表英语.xlsx", "土拨鼠术语表英语_约束完整.xlsx"],
            )

    def test_auto_discovers_both_english_and_indonesian_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "通用术语表英语.xlsx").write_text("common-en", encoding="utf-8")
            (root / "通用术语表印尼.xlsx").write_text("common-idn", encoding="utf-8")

            project = root / "土拨鼠"
            project.mkdir()
            (project / "土拨鼠英语整体校对.xlsx").write_text("lang-en", encoding="utf-8")
            (project / "土拨鼠印尼语整体校对.xlsx").write_text("lang-idn", encoding="utf-8")
            (project / "土拨鼠术语表英语_约束完整.xlsx").write_text("term-en", encoding="utf-8")
            (project / "土拨鼠术语表印尼_约束完整.xlsx").write_text("term-idn", encoding="utf-8")

            tasks = discover_workspace_tasks(root, lang="auto")

            self.assertEqual(
                [(task.project_name, task.lang) for task in tasks],
                [("土拨鼠", "en"), ("土拨鼠", "idn")],
            )


if __name__ == "__main__":
    unittest.main()
