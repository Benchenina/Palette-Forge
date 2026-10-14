"""Pixel Palette Forge — desktop color ramp generator (pywebview)."""
import base64
import os
import shutil
import subprocess
import sys
import tempfile

import webview


def get_resource_path(relative_path: str) -> str:
    """Return absolute path to a resource, compatible with dev and PyInstaller.

    PyInstaller bundles data files under ``sys._MEIPASS``; in development
    we resolve relative to this script's directory.
    """
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


class PaletteAPI:
    """JS-callable API exposed to the webview frontend."""

    def __init__(self):
        self.window = None

    def save_palette_png(self, base64_data: str):
        """Save a PNG Data URL payload via a native OS Save File dialog.

        Args:
            base64_data: Full data URL (``data:image/png;base64,...``)
                         or a raw base64 string.

        Returns:
            Dict with ``ok`` / ``path`` or ``error`` / ``cancelled`` status.
        """
        if not self.window:
            return {"ok": False, "error": "No window reference"}

        result = self.window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename="palette.png",
        )
        if not result:
            return {"ok": False, "cancelled": True}

        # create_file_dialog may return a tuple/list or a plain string
        if isinstance(result, (list, tuple)):
            if len(result) == 0:
                return {"ok": False, "cancelled": True}
            file_path = result[0]
        else:
            file_path = result

        if not file_path:
            return {"ok": False, "cancelled": True}

        # Strip the data-URL prefix if present
        payload = base64_data
        if "," in payload and payload.startswith("data:"):
            payload = payload.split(",", 1)[1]

        try:
            binary = base64.b64decode(payload)
        except Exception as exc:
            return {"ok": False, "error": f"Base64 decode failed: {exc}"}

        try:
            with open(file_path, "wb") as f:
                f.write(binary)
        except OSError as exc:
            return {"ok": False, "error": f"Write failed: {exc}"}

        return {"ok": True, "path": file_path}

    def begin_screen_pick(self):
        """Capture the desktop and switch the window to fullscreen for picking.

        Used as a fallback where the browser ``EyeDropper`` API is missing
        (e.g. WebKitGTK on Linux). The frontend displays the capture in a
        fullscreen overlay so the user can sample any on-screen pixel.

        Returns:
            Dict with ``ok`` + ``data`` (PNG data URL) or ``error``.
        """
        if not self.window:
            return {"ok": False, "error": "No window reference"}
        try:
            raw = _capture_screen_png()
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
        try:
            self.window.toggle_fullscreen()
        except Exception as exc:
            return {"ok": False, "error": f"Fullscreen failed: {exc}"}
        data_url = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        return {"ok": True, "data": data_url}

    def end_screen_pick(self):
        """Leave fullscreen mode after a screen pick finishes or is cancelled."""
        if not self.window:
            return {"ok": False, "error": "No window reference"}
        try:
            self.window.toggle_fullscreen()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


def _capture_screen_png() -> bytes:
    """Capture the full desktop and return raw PNG bytes.

    Tries native screenshot backends in order (KDE Spectacle, grim,
    GNOME, X11 tools, python-mss). Raises RuntimeError if all fail.
    """
    errors = []

    backends = [
        ["spectacle", "-b", "-f", "-n", "-o"],  # KDE (Wayland + X11)
        ["grim"],                                # wlroots Wayland
        ["gnome-screenshot", "-f"],              # GNOME
        ["scrot", "--overwrite"],                # X11
        ["import", "-window", "root"],           # X11 (ImageMagick)
    ]
    for cmd in backends:
        if shutil.which(cmd[0]) is None:
            errors.append(f"{cmd[0]}: not installed")
            continue
        tmp = tempfile.mktemp(suffix=".png")
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
            proc = subprocess.run(
                cmd + [tmp], capture_output=True, timeout=25
            )
            if proc.returncode == 0 and os.path.exists(tmp):
                with open(tmp, "rb") as f:
                    return f.read()
            err = (proc.stderr or b"").decode("utf-8", "replace").strip()
            errors.append(f"{cmd[0]}: {err or f'exit {proc.returncode}'}")
        except Exception as exc:
            errors.append(f"{cmd[0]}: {exc}")
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass

    try:
        import mss
        import mss.tools

        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[0])
            return mss.tools.to_png(shot.rgb, shot.size)
    except ImportError:
        errors.append("mss: not installed")
    except Exception as exc:
        errors.append(f"mss: {exc}")

    raise RuntimeError("No screenshot backend worked (" + "; ".join(errors) + ")")


def main():
    api = PaletteAPI()
    html_path = get_resource_path("index.html")
    window = webview.create_window(
        "PIXEL PALETTE FORGE",
        url=html_path,
        js_api=api,
        width=1180,
        height=820,
        min_size=(980, 700),
    )
    api.window = window
    webview.start(debug=False)


if __name__ == "__main__":
    main()
