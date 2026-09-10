from __future__ import annotations

import json
import os


class Config:
    def __init__(self, path: str) -> None:
        self.path = path
        self.selected_targets: list[str] = []

    def load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data.get("selected_targets"), list):
                self.selected_targets = [str(item) for item in data["selected_targets"]]
        except (OSError, json.JSONDecodeError):
            self.selected_targets = []

    def save(self) -> None:
        data = {"selected_targets": self.selected_targets}
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)
