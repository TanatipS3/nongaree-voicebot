import xml.etree.ElementTree as ET
from pathlib import Path

EYES_SRC_DIR = Path("avatar_extraction/botset/eyes")
AVATAR_DIR = Path("public/avatar")

ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
ET.register_namespace("c2pa", "http://c2pa.org/manifest")

def extract_images_from_svg(filepath):
    tree = ET.parse(filepath)
    root = tree.getroot()
    images = []
    
    for elem in root.iter():
        if elem.tag.split("}")[-1] == "image":
            for k, v in elem.attrib.items():
                if v.startswith("data:image"):
                    images.append(v)
                    break
    return images

def build_corrected_eye_svg(images_list, output_path):
    if len(images_list) < 4:
        raise ValueError(f"Expected at least 4 images, got {len(images_list)}")
        
    left_mask_data = images_list[0]
    right_mask_data = images_list[1]
    left_visible_data = images_list[2]
    right_visible_data = images_list[3]
    
    svg_template = f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1920" zoomAndPan="magnify" viewBox="0 0 1440 809.999993" height="1080" preserveAspectRatio="xMidYMid meet" version="1.0">
  <defs>
    <filter x="0%" y="0%" width="100%" height="100%" id="5862a0397f">
      <feColorMatrix values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 1 0" color-interpolation-filters="sRGB" />
    </filter>
    <filter x="0%" y="0%" width="100%" height="100%" id="8aaee31448">
      <feColorMatrix values="0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0.2126 0.7152 0.0722 0 0" color-interpolation-filters="sRGB" />
    </filter>
    <clipPath id="8281224ace">
      <rect x="0" width="870" y="0" height="401" />
    </clipPath>
    <clipPath id="5ca783a3c1">
      <path d="M 0.429688 1.125 L 392.875 1.125 L 392.875 400 L 0.429688 400 Z M 0.429688 1.125 " clip-rule="nonzero" />
    </clipPath>
    <clipPath id="7253218925">
      <path d="M 477.125 1.125 L 869.570312 1.125 L 869.570312 400 L 477.125 400 Z M 477.125 1.125 " clip-rule="nonzero" />
    </clipPath>
    <mask id="6c8c91002c">
      <g filter="url(#5862a0397f)">
        <g filter="url(#8aaee31448)" transform="matrix(2.217202, 0, 0, 2.217202, 0.428312, 1.125879)">
          <image x="0" y="0" width="177" height="180" preserveAspectRatio="xMidYMid meet" xlink:href="{left_mask_data}" />
        </g>
      </g>
    </mask>
    <mask id="59c581cc35">
      <g filter="url(#5862a0397f)">
        <g filter="url(#8aaee31448)" transform="matrix(2.217202, 0, 0, 2.217202, 477.12676, 1.125879)">
          <image x="0" y="0" width="177" height="180" preserveAspectRatio="xMidYMid meet" xlink:href="{right_mask_data}" />
        </g>
      </g>
    </mask>
  </defs>
  <g transform="matrix(1, 0, 0, 1, 285, 211)">
    <g clip-path="url(#8281224ace)">
      <g clip-path="url(#5ca783a3c1)">
        <g mask="url(#6c8c91002c)">
          <g transform="matrix(2.217202, 0, 0, 2.217202, 0.428312, 1.125879)">
            <image x="0" y="0" width="177" height="180" preserveAspectRatio="xMidYMid meet" xlink:href="{left_visible_data}" />
          </g>
        </g>
      </g>
      <g clip-path="url(#7253218925)">
        <g mask="url(#59c581cc35)">
          <g transform="matrix(2.217202, 0, 0, 2.217202, 477.12676, 1.125879)">
            <image x="0" y="0" width="177" height="180" preserveAspectRatio="xMidYMid meet" xlink:href="{right_visible_data}" />
          </g>
        </g>
      </g>
    </g>
  </g>
</svg>
"""
    output_path.write_text(svg_template, encoding="utf-8")
    print(f"Successfully wrote corrected SVG to {output_path}")

def main():
    print("Preparing and fixing 5 eye SVGs...")
    for i in range(1, 6):
        src_name = f"eye {i}.svg"
        dest_name = f"eye_{i}.svg"
        src_path = EYES_SRC_DIR / src_name
        dest_path = AVATAR_DIR / dest_name
        
        if not src_path.exists():
            print(f"Error: {src_path} does not exist.")
            continue
            
        print(f"Extracting images from {src_name}...")
        images = extract_images_from_svg(src_path)
        print(f"Found {len(images)} images in {src_name}")
        
        build_corrected_eye_svg(images, dest_path)
        
    print("Done!")

if __name__ == "__main__":
    main()
