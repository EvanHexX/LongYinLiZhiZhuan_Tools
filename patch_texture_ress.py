# patch_texture_ress.py
# 목적:
# - sharedassets1.assets 안의 Texture2D 메타데이터를 UnityPy로 찾는다.
# - 실제 이미지 데이터가 들어있는 sharedassets1.assets.resS만 직접 패치한다.
# - .assets 파일 크기를 바꾸지 않는다.

import argparse
import shutil
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
    parser.add_argument("--assets", required=True, help="sharedassets1.assets 경로")
    parser.add_argument("--texture", required=True, help="Texture2D 이름, 예: skeleton_17")
    parser.add_argument("--png", required=True, help="교체할 PNG 경로")
    parser.add_argument("--out", default="patched_out", help="출력 폴더")
    parser.add_argument("--no-flip-y", action="store_true", help="상하반전 없이 저장")
    parser.add_argument("--path-id", type=int, help="Texture2D PathID로 직접 지정")
    args = parser.parse_args()

    assets_path = Path(args.assets).resolve()
    png_path = Path(args.png).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not assets_path.exists():
        raise FileNotFoundError(assets_path)
    if not png_path.exists():
        raise FileNotFoundError(png_path)

    env = UnityPy.load(str(assets_path))

    target_obj = None
    target_data = None

    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue

        if args.path_id is not None and obj.path_id != args.path_id:
            continue

        data = obj.read(check_read=False)

        tex_name = getattr(data, "name", None) or getattr(data, "m_Name", None)

        if args.path_id is not None or tex_name == args.texture:
            target_obj = obj
            target_data = data
            break

    if target_data is None:
        raise RuntimeError(f"Texture2D not found: {args.texture}")

    # width = target_data.m_Width
    # height = target_data.m_Height
    width = getattr(target_data, "m_Width")
    height = getattr(target_data, "m_Height")

    tex_format = str(target_data.m_TextureFormat)

    target_name = getattr(target_data, "name", None) or getattr(target_data, "m_Name", None)
    print(f"[FOUND] name={target_name}")
    print(f"[FOUND] size={width}x{height}")
    print(f"[FOUND] format={tex_format}")

    stream = target_data.m_StreamData
    offset = get_attr(stream, "offset", "Offset")
    size = get_attr(stream, "size", "Size")
    stream_path = get_attr(stream, "path", "Path", default="")

    if not stream_path:
        raise RuntimeError("This texture does not appear to use external .resS stream data.")

    expected_size = width * height * 4

    if size != expected_size:
        raise RuntimeError(
            f"Unexpected stream size. stream={size}, expected RGBA32={expected_size}. "
            "압축 포맷이거나 mipmap 포함일 수 있습니다."
        )

    img = Image.open(png_path).convert("RGBA")

    if img.size != (width, height):
        raise RuntimeError(
            f"PNG size mismatch. png={img.size}, texture={width}x{height}. "
            "첫 테스트는 반드시 원본과 같은 해상도여야 합니다."
        )

    if not args.no_flip_y:
        img = ImageOps.flip(img)

    raw = img.tobytes("raw", "RGBA")

    if len(raw) != size:
        raise RuntimeError(f"Raw byte size mismatch. raw={len(raw)}, stream={size}")

    # UnityPy의 stream path가 archive:/... 형태일 수 있으므로 파일명만 사용
    ress_name = Path(str(stream_path).replace("\\", "/")).name
    if not ress_name or ress_name == ".":
        ress_name = assets_path.name + ".resS"

    ress_path = assets_path.with_name(ress_name)

    if not ress_path.exists():
        # 흔한 케이스: sharedassets1.assets.resS
        alt = assets_path.with_name(assets_path.name + ".resS")
        if alt.exists():
            ress_path = alt
        else:
            raise FileNotFoundError(f"resS file not found: {ress_path}")

    out_assets = out_dir / assets_path.name
    out_ress = out_dir / ress_path.name

    shutil.copy2(assets_path, out_assets)
    shutil.copy2(ress_path, out_ress)

    with open(out_ress, "r+b") as f:
        f.seek(offset)
        f.write(raw)

    print("[DONE]")
    print(f"assets copied unchanged: {out_assets}")
    print(f"resS patched: {out_ress}")
    print("테스트 시 원본 sharedassets1.assets / .resS 백업 후, patched_out의 두 파일로 교체하세요.")


if __name__ == "__main__":
    main()