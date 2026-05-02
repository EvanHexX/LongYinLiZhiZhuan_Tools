# tools/extract_texture_preview.py
# 목적:
# - sharedassets1.assets 안의 Texture2D를 texture 이름 또는 pathID로 찾는다.
# - Texture2D 이미지를 PNG로 추출하여 미리보기 파일로 저장한다.

import argparse
from pathlib import Path

import UnityPy
from PIL import Image, ImageOps


def get_attr(obj, *names, default=None):
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--texture", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--path-id", type=int)
    parser.add_argument("--no-flip-y", action="store_true")
    args = parser.parse_args()

    assets_path = Path(args.assets).resolve()
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not assets_path.exists():
        raise FileNotFoundError(assets_path)

    env = UnityPy.load(str(assets_path))

    target_data = None

    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue

        if args.path_id is not None and obj.path_id != args.path_id:
            continue

        data = obj.read(check_read=False)
        tex_name = getattr(data, "name", None) or getattr(data, "m_Name", None)

        if args.path_id is not None or tex_name == args.texture:
            target_data = data
            break

    if target_data is None:
        raise RuntimeError(f"Texture2D not found: {args.texture}")

    stream = target_data.m_StreamData
    offset = get_attr(stream, "offset", "Offset")
    size = get_attr(stream, "size", "Size")
    stream_path = get_attr(stream, "path", "Path", default="")

    width = getattr(target_data, "m_Width")
    height = getattr(target_data, "m_Height")

    if not stream_path:
        img = target_data.image
        img.save(out_path)
        print(str(out_path))
        return

    ress_name = Path(str(stream_path).replace("\\", "/")).name
    if not ress_name or ress_name == ".":
        ress_name = assets_path.name + ".resS"

    ress_path = assets_path.with_name(ress_name)

    if not ress_path.exists():
        alt = assets_path.with_name(assets_path.name + ".resS")
        if alt.exists():
            ress_path = alt
        else:
            raise FileNotFoundError(f"resS file not found: {ress_path}")

    expected_size = width * height * 4

    if size != expected_size:
        raise RuntimeError(
            f"Unexpected stream size. stream={size}, expected={expected_size}. "
            "현재 미리보기는 RGBA32 외부 resS 텍스처 기준입니다."
        )

    with open(ress_path, "rb") as f:
        f.seek(offset)
        raw = f.read(size)

    img = Image.frombytes("RGBA", (width, height), raw)

    if not args.no_flip_y:
        img = ImageOps.flip(img)

    img.save(out_path)
    print(str(out_path))


if __name__ == "__main__":
    main()