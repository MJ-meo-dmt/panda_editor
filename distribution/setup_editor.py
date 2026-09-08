"""Panda3D build_apps packaging foundation for Panda Editor.

Run from the project root with:
    python distribution/setup_editor.py build_apps

This is intentionally kept separate from normal development startup.
"""
from setuptools import setup

setup(
    name='PandaEditor',
    version='0.4.8',
    options={
        'build_apps': {
            'console_apps': {
                'PandaEditor': 'run_editor.py',
            },
            'log_filename': '$USER_APPDATA/PandaEditor/output.log',
            'log_append': False,
            'include_patterns': [
                'ui/**/*',
                'assets/**/*',
                'scripts/**/*',
                'prefabs/**/*',
                'project_templates/**/*',
                'project_settings.json',
            ],
            'plugins': [
                'pandagl',
                'p3openal_audio',
                'p3ffmpeg',
            ],
        }
    },
)
