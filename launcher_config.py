from __future__ import annotations

import json
import os


DEFAULT_PROFILE_NAME = "默认存档"


class Config:
    def __init__(self, path: str) -> None:
        self.path = path
        self.profiles: dict[str, list[str]] = {}
        self.active_profile = ""

    def load(self) -> None:
        data: dict[str, object] = {}
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as file:
                    loaded = json.load(file)
                if isinstance(loaded, dict):
                    data = loaded
            except (OSError, json.JSONDecodeError):
                data = {}

        profiles = data.get("profiles")
        if isinstance(profiles, dict):
            for name, targets in profiles.items():
                if isinstance(name, str) and isinstance(targets, list):
                    self.profiles[name] = [str(item) for item in targets]

        legacy_targets = data.get("selected_targets")
        if not self.profiles and isinstance(legacy_targets, list):
            self.profiles[DEFAULT_PROFILE_NAME] = [str(item) for item in legacy_targets]

        if not self.profiles:
            self.profiles[DEFAULT_PROFILE_NAME] = []

        active = data.get("active_profile")
        if isinstance(active, str) and active in self.profiles:
            self.active_profile = active
        else:
            self.active_profile = next(iter(self.profiles))

    def save(self) -> None:
        if not self.profiles:
            self.profiles[DEFAULT_PROFILE_NAME] = []
        if self.active_profile not in self.profiles:
            self.active_profile = next(iter(self.profiles))

        data = {
            "version": 2,
            "active_profile": self.active_profile,
            "profiles": self.profiles,
        }
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    def profile_names(self) -> list[str]:
        return list(self.profiles.keys())

    def get_profile(self, name: str) -> list[str]:
        return list(self.profiles.get(name, []))

    def set_profile(self, name: str, targets: list[str]) -> None:
        self.profiles[name] = list(targets)
        self.active_profile = name

    def rename_profile(self, old_name: str, new_name: str) -> bool:
        if old_name not in self.profiles or new_name in self.profiles:
            return False

        renamed: dict[str, list[str]] = {}
        for name, targets in self.profiles.items():
            if name == old_name:
                renamed[new_name] = targets
            else:
                renamed[name] = targets
        self.profiles = renamed
        if self.active_profile == old_name:
            self.active_profile = new_name
        return True

    def delete_profile(self, name: str) -> bool:
        if name not in self.profiles or len(self.profiles) <= 1:
            return False
        del self.profiles[name]
        if self.active_profile == name:
            self.active_profile = next(iter(self.profiles))
        return True

    @property
    def selected_targets(self) -> list[str]:
        return self.get_profile(self.active_profile)

    @selected_targets.setter
    def selected_targets(self, targets: list[str]) -> None:
        self.set_profile(self.active_profile or DEFAULT_PROFILE_NAME, targets)
