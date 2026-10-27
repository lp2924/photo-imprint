"""照片印迹 —— 批量给照片加上拍摄时间和地点水印。

用法：
    界面模式      python app.py
    命令行模式    python app.py --cli -i 输入目录 -o 输出目录 --place 杭州市西湖区
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from core import __version__
from core import config_store, exif_reader, layout, processor, watermark
from core.geo import DETAIL_LABELS, DETAIL_LEVELS, GeoResolver, normalize_slots
from core.paths import CACHE_FILE


def _parse_color(text: str) -> tuple[int, int, int]:
    raw = (text or "").strip().lstrip("#")
    if len(raw) != 6:
        return (255, 255, 255)
    try:
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return (255, 255, 255)


def _auto_color(style: str) -> tuple[int, int, int]:
    """拍立得是白边，白字会隐形，所以默认色跟着样式走。"""
    return (58, 58, 56) if style == "C" else (255, 255, 255)


def _default_key() -> str:
    """Key 存 config.json（DPAPI 密文）或环境变量里，不硬编码进代码。"""
    return config_store.api_key()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="照片印迹", description="批量给照片添加时间地点水印")
    parser.add_argument("--version", action="version", version=f"照片印迹 {__version__}")
    parser.add_argument("--cli", action="store_true", help="命令行模式，不带则打开界面")
    parser.add_argument("-i", "--input", help="输入目录")
    parser.add_argument("-o", "--output", help="输出目录")
    parser.add_argument("--style", default="B", choices=["A", "B", "C"], help="水印样式")
    parser.add_argument("--paper", default=layout.DEFAULT_PAPER,
                        choices=list(layout.PAPER_PRESETS), help="输出纸型")
    parser.add_argument("--fill", action="store_true",
                        help="裁切铺满纸型，默认是补白不裁切")
    parser.add_argument("--place-mode", default="auto", choices=["auto", "manual"],
                        help="auto=读 EXIF GPS，manual=全批统一地点")
    parser.add_argument("--place", default="", help="手动地点 / 无 GPS 时的兜底地点")
    parser.add_argument("--place-detail", default="district",
                        choices=list(DETAIL_LEVELS),
                        help="地点详细程度预设：" + "、".join(
                            f"{k}={DETAIL_LABELS[k]}" for k in DETAIL_LEVELS))
    parser.add_argument("--place-slots", default="",
                        help="自定义地名层级，逗号分隔，可选 province,city,district,township,road；"
                             "填了就以它为准，例：province,district → 甘肃 会宁")
    parser.add_argument("--place-style", default="short", choices=["short", "full"],
                        help="地名写法：short=短写（甘肃 会宁），full=全称连写（甘肃省白银市会宁县）")
    parser.add_argument("--date-format", default="%Y.%m.%d %H:%M",
                        help="strftime 时间格式，传空字符串则不显示时间")
    parser.add_argument("--color", default=None,
                        help="文字颜色，如 #FFFFFF；不填则按样式自动（拍立得用深灰，其余用白色）")
    parser.add_argument("--position", default="bottom-left",
                        choices=[key for key, _ in watermark.POSITIONS],
                        help="水印位置（九宫格）")
    parser.add_argument("--outline", default="solid",
                        choices=[key for key, _ in watermark.OUTLINE_STYLES],
                        help="描边样式")
    parser.add_argument("--outline-color", default="auto",
                        help="描边颜色，auto=跟随文字反色，或 #RRGGBB")
    parser.add_argument("--outline-width", type=float, default=3.0,
                        help="描边粗细，占字号的百分比（1~8，默认 3）")
    parser.add_argument("--key", default=None,
                        help="高德 Web 服务 Key，默认读环境变量 PHOTOIMPRINT_AMAP_KEY 或 config.json")
    parser.add_argument("--no-recursive", action="store_true", help="不递归子目录")
    parser.add_argument("--quality", type=int, default=95, help="JPEG 质量 1-100")
    parser.add_argument("--workers", type=int, default=4, help="并发线程数")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    if not args.input or not args.output:
        print("缺少 -i / -o 参数", file=sys.stderr)
        return 2

    input_dir = Path(args.input).expanduser()
    output_dir = Path(args.output).expanduser()
    if not input_dir.is_dir():
        print(f"输入目录不存在：{input_dir}", file=sys.stderr)
        return 2

    place_slots = normalize_slots(
        [s.strip() for s in args.place_slots.split(",") if s.strip()] or args.place_detail)

    cfg = processor.JobConfig(
        output_dir=output_dir,
        style=args.style,
        paper=args.paper,
        fill_mode="crop" if args.fill else "pad",
        place_mode=args.place_mode,
        manual_place=args.place,
        place_slots=place_slots,
        place_style=args.place_style,
        date_format=args.date_format,
        color=_parse_color(args.color) if args.color else _auto_color(args.style),
        position=args.position,
        outline_style=args.outline,
        outline_color=(None if args.outline_color.lower() == "auto"
                       else _parse_color(args.outline_color)),
        outline_width=max(0.004, min(0.10, args.outline_width / 100.0)),
        recursive=not args.no_recursive,
        jpeg_quality=max(1, min(100, args.quality)),
    )
    files = processor.collect_files(input_dir, cfg.recursive, exclude=[output_dir])
    if not files:
        print("没找到可处理的照片")
        return 1

    resolver = GeoResolver(api_key=args.key if args.key is not None else _default_key(),
                           cache_file=CACHE_FILE)
    print(f"共 {len(files)} 张，样式 {args.style}，纸型 {args.paper}")

    started = time.time()
    ok_count = 0
    fail: list[processor.JobResult] = []

    def on_progress(done: int, total: int, result: processor.JobResult) -> None:
        nonlocal ok_count
        if result.ok:
            ok_count += 1
            tag = result.place or "无地点"
            print(f"[{done}/{total}] {result.src.name} -> {result.dst.name}  ({tag})")
        else:
            fail.append(result)
            print(f"[{done}/{total}] 失败 {result.src.name}: {result.error}")

    results = processor.process_batch(files, cfg, resolver, input_root=input_dir,
                                      on_progress=on_progress, workers=args.workers)

    elapsed = time.time() - started
    print(f"\n完成 {ok_count}/{len(results)}，耗时 {elapsed:.1f}s，输出目录 {output_dir}")
    if resolver.last_error:
        print(f"地图服务提示：{resolver.last_error}")
    if fail:
        print("失败清单：")
        for item in fail:
            print(f"  {item.src}  {item.error}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cli:
        return run_cli(args)

    from ui.main_window import run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
