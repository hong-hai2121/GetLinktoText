import argparse
import sys

from src import config
from src.services.get_text import GetTextService


def parse_args():
    parser = argparse.ArgumentParser(description="Run GetTextFromLink without GUI.")
    parser.add_argument(
        "--model",
        default=config.MODEL_NAME,
        help="(Bị bỏ qua) Dự án này luôn dùng large-v3.pt tại WHISPER_MODEL_FILE.",
    )
    parser.add_argument(
        "--title-mode",
        action="store_true",
        help="Enable title/description/tag mode (chunked recognition).",
    )
    parser.add_argument(
        "--title-submode",
        choices=["full", "title_only", "content_only"],
        default="full",
        help="Title mode behavior when --title-mode is enabled.",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=config.DEFAULT_MAX_CHUNKS,
        help="Maximum chunks to recognize in title mode.",
    )
    parser.add_argument(
        "--links-file",
        default=config.LINKS_FILE,
        help="Path to link list file.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    config.LINKS_FILE = args.links_file
    service = GetTextService()

    try:
        service.initialize_whisper()
    except Exception as exc:
        print(f"❌ Không import được torch/whisper: {exc}")
        return 1

    service.configure_runtime(
        model_name=args.model,
        use_title_mode=args.title_mode,
        title_submode=args.title_submode,
        max_chunks=args.max_chunks,
    )

    try:
        service.load_model(args.model)
    except Exception as exc:
        print(f"❌ Lỗi khi tải model: {exc}")
        return 1

    service.process_videos()
    return 0


if __name__ == "__main__":
    sys.exit(main())
