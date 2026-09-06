"""Console-free launcher: on Windows, .pyw files run with pythonw.exe,
so double-clicking this file starts the widget with no console window.
Run main.py with python.exe when you want console output for debugging."""

from main import main

if __name__ == "__main__":
    raise SystemExit(main())
