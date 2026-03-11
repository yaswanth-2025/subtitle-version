"""
SRT Compare - Desktop Application Launcher
Starts the FastAPI backend, serves the HTML frontend, and opens the browser.
Works on both Windows and Linux.
"""
import sys
import os
import platform
import socket
import webbrowser
import threading
import time

IS_WINDOWS = platform.system() == "Windows"


def get_base_path():
    """Get the base path for resources (works for both dev and PyInstaller)."""
    if getattr(sys, "frozen", False):
        # Running as PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running as script
        return os.path.dirname(os.path.abspath(__file__))


def find_free_port(start=8000, end=8100):
    """Find a free port to use."""
    for port in range(start, end):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("127.0.0.1", port))
            sock.close()
            return port
        except OSError:
            continue
    return 8000


def open_browser(port):
    """Open browser after a short delay to let the server start."""
    time.sleep(2.5)
    url = f"http://127.0.0.1:{port}"
    print(f"  Opening browser at {url}")
    webbrowser.open(url)


def main():
    # Set console title on Windows
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("SRT Compare")
        except Exception:
            pass

    # Set up paths
    base_path = get_base_path()
    os.chdir(base_path)

    # Add base path to Python path so imports work
    if base_path not in sys.path:
        sys.path.insert(0, base_path)

    # Find a free port
    port = find_free_port()

    print("=" * 50)
    print("  SRT Compare - Desktop Application")
    print("=" * 50)
    print(f"  Base path : {base_path}")
    print(f"  Platform  : {platform.system()} {platform.machine()}")
    print(f"  Server    : http://127.0.0.1:{port}")
    print(f"  Database  : SQLite (zero config)")
    print(f"  Press Ctrl+C to quit")
    print("=" * 50)

    # Open browser in background thread
    browser_thread = threading.Thread(target=open_browser, args=(port,), daemon=True)
    browser_thread.start()

    # Import and configure uvicorn
    import uvicorn

    # Run the FastAPI server
    try:
        uvicorn.run(
            "main:app",
            host="127.0.0.1",
            port=port,
            log_level="info",
            reload=False,
        )
    except KeyboardInterrupt:
        print("\n  Shutting down SRT Compare...")
        sys.exit(0)


if __name__ == "__main__":
    main()
