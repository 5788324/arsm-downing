import flet as ft

# Premium Color Palette
BG_DARK = "#0F172A"
BG_SURFACE = "#1E293B"
BG_SURFACE_LIGHT = "#334155"

ACCENT_PRIMARY = "#8B5CF6"
ACCENT_SECONDARY = "#3B82F6"
ACCENT_NEON = "#06B6D4"

TEXT_PRIMARY = "#F8FAFC"
TEXT_SECONDARY = "#94A3B8"

SUCCESS = "#10B981"
WARNING = "#F59E0B"
ERROR = "#EF4444"

class PremiumTheme:
    @staticmethod
    def get_theme():
        return ft.Theme(
            color_scheme_seed=ACCENT_PRIMARY,
            font_family="Inter",
            color_scheme=ft.ColorScheme(
                background=BG_DARK,
                surface=BG_SURFACE,
                primary=ACCENT_PRIMARY,
                secondary=ACCENT_SECONDARY,
                error=ERROR,
                on_surface=TEXT_PRIMARY,
                on_background=TEXT_PRIMARY,
            )
        )

class Styles:
    @staticmethod
    def glass_container(content: ft.Control, padding=20, border_radius=15, width=None, height=None, expand=False):
        return ft.Container(
            content=content,
            padding=padding,
            border_radius=border_radius,
            bgcolor=ft.colors.with_opacity(0.4, BG_SURFACE),
            border=ft.border.all(1, ft.colors.with_opacity(0.2, "white")),
            blur=ft.Blur(10, 10, ft.BlurTileMode.MIRROR),
            width=width,
            height=height,
            expand=expand
        )

    @staticmethod
    def gradient_text(text: str, size: int = 24, weight=ft.FontWeight.BOLD):
        return ft.Text(
            text,
            size=size,
            weight=weight,
            spans=[
                ft.TextSpan(
                    text,
                    style=ft.TextStyle(
                        foreground=ft.Paint(
                            gradient=ft.PaintLinearGradient(
                                (0, 0), (200, 0), colors=[ACCENT_PRIMARY, ACCENT_NEON]
                            )
                        )
                    )
                )
            ]
        )
