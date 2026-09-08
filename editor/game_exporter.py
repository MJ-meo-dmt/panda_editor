from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from editor.config import ROOT
from editor.project_settings import ProjectSettings


def _safe_executable(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "", str(value or "Panda3DGame").strip())
    return value or "Panda3DGame"


def _safe_version(value: str) -> str:
    value = str(value or "0.1.0").strip()
    if re.fullmatch(r"\d+(?:\.\d+){0,3}(?:[-+._A-Za-z0-9]*)?", value):
        return value
    return "0.1.0"


class WindowsGameExporter:
    """Generate Panda3D build_apps / bdist_apps Windows x64 distributions."""

    def __init__(self, log: Callable[[str], None], emit: Callable[[str, dict], None]) -> None:
        self.log = log
        self.emit = emit
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._operation = "build"
        self._started_at = 0.0

    def status(self) -> dict:
        proc = self.process
        code = proc.poll() if proc else None
        return {
            "running": bool(proc and code is None),
            "pid": proc.pid if proc else None,
            "exit_code": code,
            "operation": self._operation,
        }

    def _output_dir(self, settings: ProjectSettings) -> Path:
        return (ROOT / str(settings.export_output_dir or "build_exports")).resolve()

    def _package_dir(self, settings: ProjectSettings) -> Path:
        return self._output_dir(settings) / "packages"

    def validate(self, settings: ProjectSettings) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        info: list[str] = []

        startup_rel = str(settings.startup_scene or "").strip()
        if not startup_rel:
            errors.append("No startup scene is configured.")
        else:
            startup = (ROOT / startup_rel).resolve()
            if ROOT.resolve() not in startup.parents or not startup.is_file():
                errors.append(f"Startup scene was not found inside the project: {startup_rel}")

        if not (ROOT / "run_game.py").is_file():
            errors.append("run_game.py is missing.")
        if not (ROOT / "runtime" / "standalone.py").is_file():
            errors.append("runtime/standalone.py is missing.")
        if not (ROOT / "project_settings.json").is_file():
            errors.append("project_settings.json is missing.")

        try:
            output = self._output_dir(settings)
            if ROOT.resolve() not in output.parents or output == ROOT.resolve():
                errors.append("Export output directory must be a child of the project folder.")
        except Exception:
            errors.append("Export output directory is invalid.")

        scripts_root = ROOT / "scripts"
        if scripts_root.exists():
            for script_file in scripts_root.rglob("*.py"):
                if script_file.name == "__init__.py":
                    continue
                parts = script_file.relative_to(ROOT).with_suffix("").parts
                if not all(part.isidentifier() for part in parts):
                    errors.append(
                        f"Script path cannot be frozen as a Python module: {script_file.relative_to(ROOT).as_posix()}"
                    )

        sanitized = _safe_executable(settings.export_executable_name)
        if sanitized != settings.export_executable_name:
            warnings.append(f"Executable name will be sanitized to {sanitized}.")
        if settings.export_build_type == "release":
            warnings.append(
                "Release is a GUI build. Runtime errors are written to AppData instead of a console window."
            )

        icon_rel = str(settings.export_icon_path or "").strip()
        if icon_rel:
            icon = (ROOT / icon_rel).resolve()
            if ROOT.resolve() not in icon.parents or not icon.is_file():
                errors.append(f"Export icon was not found inside the project: {icon_rel}")
            elif icon.suffix.lower() not in {'.png','.jpg','.jpeg'}:
                errors.append("Export icon must be PNG or JPEG for Panda3D icon generation.")
            else:
                info.append(f"Application icon: {icon_rel}")
        else:
            warnings.append("No application icon configured; Panda3D default executable icon will be used.")

        package_format = str(settings.export_package_format or 'zip').lower()
        if package_format == 'nsis':
            makensis = shutil.which('makensis') or shutil.which('makensis.exe')
            if not makensis:
                errors.append("NSIS packaging requires makensis.exe on PATH. Install NSIS or switch Package Format to ZIP.")
            else:
                info.append(f"NSIS detected: {makensis}")
        else:
            info.append("ZIP packaging uses Panda3D bdist_apps and requires no external installer tool.")

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "platform": "win_amd64",
            "package_format": package_format,
        }

    def _script_modules(self) -> list[str]:
        modules: list[str] = []
        scripts_root = ROOT / "scripts"
        if scripts_root.exists():
            for script_file in sorted(scripts_root.rglob("*.py")):
                if script_file.name == "__init__.py":
                    continue
                rel_parts = script_file.relative_to(ROOT).with_suffix("").parts
                if all(part.isidentifier() for part in rel_parts):
                    modules.append(".".join(rel_parts))
        return modules

    def generate(self, settings: ProjectSettings) -> dict:
        validation = self.validate(settings)
        if not validation["ok"]:
            return validation

        generated = ROOT / ".panda_export"
        generated.mkdir(parents=True, exist_ok=True)

        requirements = generated / "game_requirements.txt"
        requirements_text = "panda3d>=1.10.15\npanda3d-gltf>=1.3.0\n"
        pipeline = str(settings.world_render_pipeline or 'builtin').lower()
        if pipeline == 'simplepbr':
            requirements_text += "panda3d-simplepbr>=0.13.1\n"
        elif pipeline == 'complexpbr':
            requirements_text += "panda3d-complexpbr\n"
        requirements.write_text(requirements_text, encoding="utf-8")

        exe_name = _safe_executable(settings.export_executable_name)
        app_name = str(settings.export_app_name or settings.game_window_title or "Panda3D Game")
        version = _safe_version(settings.export_version)
        output = self._output_dir(settings)
        packages = self._package_dir(settings)
        app_key = "console_apps" if settings.export_build_type == "development" else "gui_apps"
        plugins = ["pandagl", "p3openal_audio"]
        if settings.export_include_ffmpeg:
            plugins.append("p3ffmpeg")
        script_modules = self._script_modules()
        icon_rel = str(settings.export_icon_path or '').strip()
        package_format = str(settings.export_package_format or 'zip').lower()

        setup_lines = [
            "# Generated by Panda Editor 0.4.36. Safe to delete; it will be regenerated.",
            "from setuptools import setup",
            "",
            "setup(",
            f"    name={app_name!r},",
            f"    version={version!r},",
            f"    author={str(settings.export_company or '')!r},",
            f"    description={str(settings.export_description or '')!r},",
            "    options={",
            "        'build_apps': {",
            f"            {app_key!r}: {{{exe_name!r}: 'run_game.py'}},",
            "            'platforms': ['win_amd64'],",
            f"            'requirements_path': {str(requirements)!r},",
            f"            'build_base': {str(output)!r},",
            "            'include_patterns': [",
            "                'project_settings.json',",
            "                '**/*.pscene',",
            "                'assets/**/*',",
            "                'scripts/**/*',",
            "                'prefabs/**/*',",
            "                'project_templates/**/*',",
            "            ],",
            "            'exclude_patterns': [",
            "                'ui/**/*', 'distribution/**/*', '.panda_export/**/*',",
            "                'build_exports/**/*', '.panda_editor/**/*', '**/__pycache__/**/*', '**/*.pyc',",
            "            ],",
            f"            'plugins': {plugins!r},",
            f"            'include_modules': {{'*': {script_modules!r}}},",
            "            'bam_model_extensions': ['.gltf', '.glb', '.egg'],",
            f"            'prefer_discrete_gpu': {bool(settings.export_prefer_discrete_gpu)!r},",
            f"            'use_optimized_wheels': {settings.export_build_type == 'release'!r},",
            f"            'log_filename': {'$USER_APPDATA/' + exe_name + '/logs/output.log'!r},",
            "            'log_append': False,",
        ]
        if icon_rel:
            setup_lines.append(f"            'icons': {{{exe_name!r}: [{icon_rel!r}]}},")
        setup_lines += [
            "        },",
            "        'bdist_apps': {",
            f"            'installers': {{'win_amd64': {package_format!r}}},",
            "        },",
            "    },",
            ")",
            "",
        ]
        setup_path = generated / "setup_game.py"
        setup_path.write_text("\n".join(setup_lines), encoding="utf-8")

        manifest = {
            "generator": "Panda Editor 0.4.36",
            "platform": "win_amd64",
            "application_name": app_name,
            "executable_name": exe_name,
            "version": version,
            "company": settings.export_company,
            "description": settings.export_description,
            "build_type": settings.export_build_type,
            "startup_scene": settings.startup_scene,
            "output_dir": output.relative_to(ROOT).as_posix(),
            "package_dir": packages.relative_to(ROOT).as_posix(),
            "package_format": package_format,
            "icon": icon_rel,
            "plugins": plugins,
            "prefer_discrete_gpu": bool(settings.export_prefer_discrete_gpu),
            "bam_model_extensions": [".gltf", ".glb", ".egg"],
            "script_modules": script_modules,
        }
        (generated / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        return {
            "ok": True,
            "setup": str(setup_path),
            "requirements": str(requirements),
            "manifest": manifest,
            "output": str(output),
            "packages": str(packages),
        }

    def clean(self, settings: ProjectSettings) -> dict:
        if self.status()["running"]:
            return {"ok": False, "error": "A build is currently running."}
        output = self._output_dir(settings)
        if ROOT.resolve() not in output.parents or output == ROOT.resolve():
            return {"ok": False, "error": "Unsafe export output path."}
        if output.exists():
            shutil.rmtree(output)
        dist = ROOT / 'dist'
        if dist.exists():
            shutil.rmtree(dist)
        self.log(f"Export: cleaned {output.relative_to(ROOT).as_posix()} and packaging staging output.")
        return {"ok": True}

    def start(self, settings: ProjectSettings, operation: str = "build") -> dict:
        with self._lock:
            if self.status()["running"]:
                return {"ok": False, "error": "A Windows export operation is already running."}

            generated = self.generate(settings)
            if not generated.get("ok"):
                return generated

            operation = "package" if operation == "package" else "build"
            command = "bdist_apps" if operation == "package" else "build_apps"
            setup_path = Path(generated["setup"])
            args = [sys.executable, str(setup_path), command]
            if operation == 'package':
                package_dir = Path(generated['packages'])
                package_dir.mkdir(parents=True, exist_ok=True)
                args += ['--dist-dir', str(package_dir)]
            self._operation = operation
            self._started_at = time.time()
            self.emit("build_state_changed", {
                "state": "starting",
                "operation": operation,
                "command": " ".join(args),
                "output": generated["output"],
            })

            try:
                creationflags = 0
                if os.name == "nt" and settings.export_build_type == "release":
                    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                self.process = subprocess.Popen(
                    args,
                    cwd=str(ROOT),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True,
                    creationflags=creationflags,
                )
            except Exception as exc:
                self.process = None
                return {"ok": False, "error": str(exc)}

            self.thread = threading.Thread(target=self._pump, args=(generated,), daemon=True)
            self.thread.start()
            return {
                "ok": True,
                "pid": self.process.pid,
                "operation": operation,
                "output": generated["output"],
                "packages": generated["packages"],
                "manifest": generated["manifest"],
            }

    def package(self, settings: ProjectSettings) -> dict:
        return self.start(settings, "package")

    def _artifacts(self, generated: dict) -> list[dict]:
        paths: list[Path] = []
        if self._operation == 'package':
            root = Path(generated.get('packages') or '')
            if root.exists():
                paths.extend(p for p in root.iterdir() if p.is_file())
        else:
            root = Path(generated.get('output') or '') / 'win_amd64'
            exe = root / (_safe_executable(generated['manifest']['executable_name']) + '.exe')
            if exe.exists():
                paths.append(exe)
        out=[]
        for p in sorted(paths, key=lambda x: x.name.lower()):
            try: size=p.stat().st_size
            except OSError: size=0
            out.append({'name':p.name,'path':str(p),'size':size})
        return out

    def _pump(self, generated: dict) -> None:
        proc = self.process
        if not proc:
            return
        self.emit("build_state_changed", {"state": "building", "operation": self._operation, "pid": proc.pid, "output": generated["output"]})
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\r\n")
                if line:
                    self.log("[Build] " + line)
                    self.emit("build_output", {"line": line})
            code = proc.wait()
        except Exception as exc:
            code = -1
            self.emit("build_output", {"line": f"Build log reader error: {exc}"})

        state = "succeeded" if code == 0 else "failed"
        artifacts = self._artifacts(generated) if code == 0 else []
        report = {
            'generator':'Panda Editor 0.4.0',
            'state':state,
            'exit_code':code,
            'operation':self._operation,
            'finished_at':time.strftime('%Y-%m-%d %H:%M:%S'),
            'manifest':generated.get('manifest',{}),
            'artifacts':artifacts,
        }
        try:
            report_path = ROOT / '.panda_export' / 'last_build_report.json'
            report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')
        except Exception:
            pass
        self.emit("build_state_changed", {"state": state, "operation": self._operation, "exit_code": code, "output": generated["output"], "artifacts": artifacts})
        self.log(f"Windows Export: {self._operation} {state} (exit code {code}).")

    def cancel(self) -> dict:
        proc = self.process
        if not proc or proc.poll() is not None:
            return {"ok": False, "error": "No build is currently running."}
        try:
            proc.terminate()
            self.emit("build_state_changed", {"state": "cancelling", "operation": self._operation})
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
