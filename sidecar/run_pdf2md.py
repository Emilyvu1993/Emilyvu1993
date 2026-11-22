"""PyInstaller entry point. `pdf2md/__main__.py` uses a relative import, which cannot be the entry script of a
frozen executable (no parent package), so the frozen build starts here with an absolute import."""
from pdf2md.rpc import main

if __name__ == "__main__":
    main()
