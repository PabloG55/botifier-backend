import uuid, os
from pydub import AudioSegment
from google.cloud import speech

def transcribe_audio(audio_path):
    wav_path = f"converted_{uuid.uuid4()}.wav"
    try:
        # load and normalize
        sound = AudioSegment.from_file(audio_path)
        sound = (sound
                 .set_channels(1)        # mono
                 .set_frame_rate(16000)  # 16 kHz
                 .set_sample_width(2)    # 2 bytes = 16 bits
                )

        sound.export(wav_path, format="wav")

        client = speech.SpeechClient()
        with open(wav_path, "rb") as audio_file:
            content = audio_file.read()

        audio = speech.RecognitionAudio(content=content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=16000,
            language_code="en-US"
        )

        response = client.recognize(config=config, audio=audio)
        text = " ".join(r.alternatives[0].transcript for r in response.results)
        return text.strip()

    finally:
        if os.path.exists(wav_path):
            os.remove(wav_path)
