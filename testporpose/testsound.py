from pathlib import Path
from openai import OpenAI

# =========================
# Configuration
# =========================

client = OpenAI(
    base_url="https://tokenmind.9meo.uk/v1",
    api_key="sk-kvkwKaUcA7AUJzM8hsf7vg",  # <-- put your API key here
)

# Folder for generated WAV files
output_dir = Path.cwd() / "tts_voices"
output_dir.mkdir(exist_ok=True)

# All voices provided by the API
voices = [
    "ped",
    "dr_wit",
    "tu",
    "pop",
    "tun",
    "poom",
    "nok",
    "dr_chai",
    "baifern",
    "bantita",
    "noon",
]

# Text used for testing
test_text = """สวัสดีค่ะ นี่คือเสียงสำหรับทดสอบระบบ
เงินเดือนห้าหมื่นบาทต่อเดือน ถ้ารับครบทั้งปีจะเป็นหกแสนบาทค่ะ
รายได้ทั้งปีเกินหนึ่งแสนสองหมื่นบาท
โดยทั่วไปควรยื่นแบบภาษีเก้าสิบเอ็ดค่ะ
ภาษีประมาณสองหมื่นหนึ่งพันห้าร้อยบาทต่อปีค่ะ"""

# =========================
# Generate audio
# =========================

for voice in voices:

    output_file = output_dir / f"{voice}.wav"

    print(f"Generating voice: {voice}")

    try:
        with client.audio.speech.with_streaming_response.create(
            model="ptm-tts-1",
            voice=voice,
            input=test_text,
            response_format="wav",
        ) as response:
            response.stream_to_file(output_file)

        print(f"  ✓ Saved: {output_file}")

    except Exception as e:
        print(f"  ✗ Failed: {voice}")
        print(f"    Error: {e}")

print("\nFinished!")
print(f"Files are in: {output_dir}")