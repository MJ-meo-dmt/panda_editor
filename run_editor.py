import multiprocessing as mp

from editor.application import PandaEditorApplication


if __name__ == '__main__':
    mp.freeze_support()
    PandaEditorApplication().run()
