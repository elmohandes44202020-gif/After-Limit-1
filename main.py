from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import edge_tts
import av

import io
import re
import wave
import asyncio
import logging
from typing import Dict, List


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Edge TTS Podcast API",
    version="2.2.0"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("edge-tts-podcast")

# ============================================================
# EDGE TTS DIAGNOSTIC
# ============================================================

@app.get("/diagnose-tts")
async def diagnose_tts():
    """
    اختبار مباشر لخدمة Edge TTS.

    يعرض إصدار المكتبة، والصوت المستخدم، ونتيجة الاتصال،
    وعدد بايتات الصوت المستلمة، ومدة الاختبار، والخطأ إن وجد.
    """

    import importlib.metadata
    import time

    started_at = time.monotonic()

    result = {
        "service": "Edge TTS Diagnostic",
        "test": "started",
        "edge_tts_version": None,
        "voice": DEFAULT_VOICE,
        "audio_received": False,
        "audio_bytes": 0,
        "duration_seconds": 0,
        "error_type": None,
        "error": None,
    }

    try:
        result["edge_tts_version"] = importlib.metadata.version("edge-tts")

        logger.info(
            "Diagnostic TTS started | version=%s | voice=%s",
            result["edge_tts_version"],
            DEFAULT_VOICE,
        )

        communicate = edge_tts.Communicate(
            text="مرحبا، هذا اختبار لاتصال خدمة توليد الصوت.",
            voice=DEFAULT_VOICE,
        )

        audio_data = bytearray()

        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                audio_data.extend(chunk["data"])

        if not audio_data:
            raise RuntimeError("Edge TTS returned no audio data.")

        result["test"] = "success"
        result["audio_received"] = True
        result["audio_bytes"] = len(audio_data)

        logger.info(
            "Diagnostic TTS succeeded | bytes=%s",
            len(audio_data),
        )

    except Exception as exc:
        result["test"] = "failed"
        result["error_type"] = type(exc).__name__

        # لا نُرجع رابط WebSocket الطويل أو معلمات الاتصال كاملة.
        error_message = str(exc).split(", url=")[0]
        result["error"] = error_message[:1000]

        logger.exception("Diagnostic TTS failed")

    finally:
        result["duration_seconds"] = round(
            time.monotonic() - started_at,
            3,
        )

    return result




# ============================================================
# SETTINGS
# ============================================================

DEFAULT_VOICE = "ar-EG-SalmaNeural"

ALLOWED_BITRATES = {
    "56k",
    "64k",
    "96k",
    "128k",
    "192k",
    "256k",
    "320k"
}

ALLOWED_FORMATS = {
    "mp3",
    "wav"
}


# ============================================================
# PAUSE STANDARD
# ============================================================

ALLOWED_PAUSES = {
    0.5,
    0.75,
    1.0,
    1.25,
    1.5,
    1.75,
    2.0,
    2.25,
    2.5,
    3.0
}

DEFAULT_AUTO_PAUSE = 0.7


# ============================================================
# REGEX
# ============================================================

# يدعم:
#
# [PAUSE:0.5]
# [PAUSE:1.0]
# [PAUSE:1.5]
#
# سواء في سطر منفصل
# أو داخل السطر نفسه.

PAUSE_PATTERN = re.compile(
    r"\[\s*PAUSE\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*\]",
    re.IGNORECASE
)


# ============================================================
# MODELS
# ============================================================

class TTSRequest(BaseModel):

    text: str

    voice: str = DEFAULT_VOICE

    rate: str = "+0%"

    pitch: str = "+0Hz"


class SpeakerConfig(BaseModel):

    voice: str

    rate: str = "+0%"

    pitch: str = "+0Hz"


class PodcastRequest(BaseModel):

    script: str

    speaker1: SpeakerConfig = Field(
        default_factory=lambda: SpeakerConfig(
            voice="ar-EG-SalmaNeural"
        )
    )

    speaker2: SpeakerConfig = Field(
        default_factory=lambda: SpeakerConfig(
            voice="ar-EG-ShakirNeural"
        )
    )

    format: str = "mp3"

    bitrate: str = "192k"

    auto_pause: bool = True

    auto_pause_duration: float = DEFAULT_AUTO_PAUSE


# ============================================================
# HOME
# ============================================================

@app.get("/")
async def home():

    return {
        "status": "online",
        "service": "Edge TTS Podcast API",
        "version": "2.2.0",
        "text_limit": None,
        "large_text_supported": True,

        "podcast_logic": {
            "mode": "automatic_line_alternation",
            "speaker_labels_required": False,
            "first_dialogue_line": "speaker1",
            "second_dialogue_line": "speaker2",
            "third_dialogue_line": "speaker1",
            "pause_changes_speaker": False
        },

        "pause_standard": [
            0.5,
            0.75,
            1.0,
            1.25,
            1.5,
            1.75,
            2.0,
            2.25,
            2.5,
            3.0
        ],

        "features": [
            "normal_tts",
            "two_speaker_podcast",
            "automatic_line_based_speaker_switching",
            "no_speaker_labels_required",
            "real_pauses",
            "inline_pause_detection",
            "strict_pause_standard",
            "pause_does_not_change_speaker",
            "automatic_transition_pause",
            "large_text_processing",
            "mp3",
            "wav",
            "multiple_bitrates",
            "retry",
            "no_application_text_limit"
        ]
    }


@app.get("/health")
async def health():

    return {
        "status": "ok",
        "edge_tts": True,
        "pyav": True,
        "text_limit": None,

        "podcast_logic": "automatic_line_alternation",

        "pause_standard": [
            0.5,
            0.75,
            1.0,
            1.25,
            1.5,
            1.75,
            2.0,
            2.25,
            2.5,
            3.0
        ]
    }


# ============================================================
# VALIDATION
# ============================================================

def validate_pause(value: float) -> float:

    """
    Validation عام للصمت الحقيقي.

    يستخدم للـ auto_pause أيضاً.
    """

    value = float(value)

    if value <= 0:

        raise ValueError(
            "Pause must be greater than 0 seconds."
        )

    if value > 30:

        raise ValueError(
            "Pause cannot be greater than 30 seconds."
        )

    return value


def validate_explicit_pause(value: float) -> float:

    """
    الـ Pause Standard الرسمي.

    القيم المسموح بها فقط:

    0.5
    0.75
    1.0
    1.25
    1.5
    1.75
    2.0
    2.25
    2.5
    3.0
    """

    value = float(value)

    if value not in ALLOWED_PAUSES:

        allowed = ", ".join(
            str(x)
            for x in sorted(ALLOWED_PAUSES)
        )

        raise ValueError(
            "Invalid PAUSE value. "
            f"Allowed values are: {allowed}"
        )

    return value


def validate_format(fmt: str):

    fmt = fmt.lower().strip()

    if fmt not in ALLOWED_FORMATS:

        raise ValueError(
            f"Unsupported format: {fmt}"
        )

    return fmt


def validate_bitrate(bitrate: str):

    bitrate = bitrate.lower().strip()

    if bitrate not in ALLOWED_BITRATES:

        raise ValueError(
            f"Unsupported bitrate: {bitrate}"
        )

    return bitrate


# ============================================================
# TEXT CHUNKING
# ============================================================

def split_large_text(
    text: str,
    max_chunk_chars: int = 3000
) -> List[str]:

    """
    يقسم النصوص الكبيرة تلقائياً.

    هذا ليس حد أحرف للمستخدم.

    المستخدم يستطيع إرسال نص كبير جداً.

    التقسيم داخلي فقط لتحسين
    استقرار Edge TTS.
    """

    text = text.strip()

    if not text:
        return []

    if len(text) <= max_chunk_chars:

        return [text]

    paragraphs = re.split(
        r"\n\s*\n",
        text
    )

    chunks = []

    for paragraph in paragraphs:

        paragraph = paragraph.strip()

        if not paragraph:

            continue

        if len(paragraph) <= max_chunk_chars:

            chunks.append(paragraph)

            continue

        sentences = re.split(
            r"(?<=[.!؟?。！])\s+",
            paragraph
        )

        current = ""

        for sentence in sentences:

            sentence = sentence.strip()

            if not sentence:

                continue

            candidate = (
                sentence
                if not current
                else current + " " + sentence
            )

            if len(candidate) <= max_chunk_chars:

                current = candidate

            else:

                if current:

                    chunks.append(current)

                if len(sentence) > max_chunk_chars:

                    for i in range(
                        0,
                        len(sentence),
                        max_chunk_chars
                    ):

                        chunks.append(
                            sentence[
                                i:i + max_chunk_chars
                            ]
                        )

                    current = ""

                else:

                    current = sentence

        if current:

            chunks.append(current)

    return chunks


# ============================================================
# EDGE TTS SINGLE CHUNK
# ============================================================

async def generate_tts_chunk(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    retries: int = 3
) -> bytes:

    last_error = None

    for attempt in range(
        1,
        retries + 1
    ):

        try:

            logger.info(
                "TTS chunk attempt %s/%s | "
                "voice=%s | chars=%s",
                attempt,
                retries,
                voice,
                len(text)
            )

            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=rate,
                pitch=pitch
            )

            audio_data = bytearray()

            async for chunk in communicate.stream():

                if chunk["type"] == "audio":

                    audio_data.extend(
                        chunk["data"]
                    )

            if not audio_data:

                raise RuntimeError(
                    "Edge TTS returned empty audio."
                )

            return bytes(audio_data)

        except Exception as e:

            last_error = e

            logger.exception(
                "TTS chunk failed."
            )

            if attempt < retries:

                await asyncio.sleep(
                    attempt * 2
                )

    raise RuntimeError(
        f"TTS failed after {retries} attempts: "
        f"{last_error}"
    )


# ============================================================
# EDGE TTS LARGE TEXT
# ============================================================

async def generate_tts_file(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    retries: int = 3
) -> bytes:

    chunks = split_large_text(
        text,
        max_chunk_chars=3000
    )

    if not chunks:

        raise RuntimeError(
            "Text is empty."
        )

    logger.info(
        "Large text processing started | "
        "characters=%s | chunks=%s",
        len(text),
        len(chunks)
    )

    all_audio = []

    for index, chunk in enumerate(
        chunks,
        start=1
    ):

        logger.info(
            "Processing TTS chunk %s/%s",
            index,
            len(chunks)
        )

        audio = await generate_tts_chunk(
            text=chunk,
            voice=voice,
            rate=rate,
            pitch=pitch,
            retries=retries
        )

        all_audio.append(audio)

    return await merge_mp3_files(
        all_audio
    )


# ============================================================
# MERGE MP3 FILES
# ============================================================

async def merge_mp3_files(
    audio_files: List[bytes]
) -> bytes:

    if not audio_files:

        raise RuntimeError(
            "No audio files to merge."
        )

    if len(audio_files) == 1:

        return audio_files[0]

    output = io.BytesIO()

    output_container = None

    try:

        output_container = av.open(
            output,
            mode="w",
            format="mp3"
        )

        output_stream = None

        for audio_bytes in audio_files:

            input_container = None

            try:

                input_container = av.open(
                    io.BytesIO(audio_bytes),
                    mode="r"
                )

                input_stream = (
                    input_container
                    .streams
                    .audio[0]
                )

                if output_stream is None:

                    sample_rate = (
                        input_stream.rate
                        or 48000
                    )

                    output_stream = (
                        output_container.add_stream(
                            "libmp3lame",
                            rate=sample_rate
                        )
                    )

                    output_stream.layout = "mono"

                    output_stream.bit_rate = 192000

                for frame in input_container.decode(
                    input_stream
                ):

                    frame = frame.reformat(
                        format="s16",
                        layout="mono"
                    )

                    frame.sample_rate = (
                        output_stream.rate
                    )

                    for packet in output_stream.encode(
                        frame
                    ):

                        output_container.mux(
                            packet
                        )

            finally:

                if input_container is not None:

                    input_container.close()

        if output_stream is not None:

            for packet in output_stream.encode():

                output_container.mux(
                    packet
                )

        output_container.close()

        output_container = None

        return output.getvalue()

    finally:

        if output_container is not None:

            output_container.close()


# ============================================================
# NORMAL TTS
# ============================================================

@app.post("/tts")
async def tts(
    data: TTSRequest
):

    if not data.text.strip():

        raise HTTPException(
            status_code=400,
            detail="Text is empty."
        )

    try:

        audio = await generate_tts_file(
            text=data.text,
            voice=data.voice,
            rate=data.rate,
            pitch=data.pitch
        )

        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition":
                    'attachment; filename="speech.mp3"'
            }
        )

    except Exception as e:

        logger.exception(
            "Normal TTS failed."
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ============================================================
# PODCAST SCRIPT PARSER
# ============================================================

def parse_podcast_script(
    script: str
):

    """
    Podcast Parser.

    ========================================================

    AUTOMATIC TWO-SPEAKER LOGIC

    لا يحتاج النص إلى:

    [SPEAKER:1]
    [SPEAKER:2]

    القاعدة:

    أول سطر كلام  -> Speaker 1
    ثاني سطر كلام -> Speaker 2
    ثالث سطر كلام -> Speaker 1
    رابع سطر كلام -> Speaker 2

    وهكذا بالتبادل.

    ========================================================

    PAUSE LOGIC

    يدعم:

    [PAUSE:0.5]
    [PAUSE:1.0]
    [PAUSE:1.5]

    سواء:

    في سطر منفصل

    أو داخل السطر.

    مهم جداً:

    الـ PAUSE لا تعتبر متحدثاً.
    الـ PAUSE لا تغير ترتيب المتحدثين.

    مثال:

    مرحباً بكم في حلقة جديدة.

    أهلاً وسهلاً بكم جميعاً.

    [PAUSE:1.0]

    اليوم سنتحدث عن موضوع مهم.

    هنا سيكون:

    السطر الأول  -> Speaker 1
    السطر الثاني -> Speaker 2
    PAUSE        -> لا تغيير
    السطر الثالث -> Speaker 1

    ========================================================

    INLINE PAUSE

    مثال:

    مرحباً بكم [PAUSE:1.0] في حلقة جديدة.

    النتيجة:

    Speaker 1:
    مرحباً بكم

    Pause:
    1.0

    Speaker 1:
    في حلقة جديدة.

    لأن السطر نفسه يعتبر Turn واحداً
    ولا يتغير المتحدث بسبب الـ PAUSE.
    """

    lines = script.splitlines()

    segments = []

    # ========================================================
    # SPEAKER ALTERNATION
    # ========================================================

    current_speaker = 1

    # ========================================================
    # PROCESS ONE DIALOGUE LINE
    # ========================================================

    def process_dialogue_line(
        text: str,
        speaker_id: int
    ):

        position = 0

        matches = list(
            PAUSE_PATTERN.finditer(
                text
            )
        )

        # ----------------------------------------------------
        # NO PAUSE
        # ----------------------------------------------------

        if not matches:

            cleaned = text.strip()

            if cleaned:

                segments.append({

                    "speaker": speaker_id,

                    "text": cleaned,

                    "pause_after": None

                })

            return


        # ----------------------------------------------------
        # INLINE PAUSES
        # ----------------------------------------------------

        for match in matches:

            before_pause = (
                text[
                    position:
                    match.start()
                ].strip()
            )

            # ------------------------------------------------
            # PAUSE VALUE
            # ------------------------------------------------

            pause_value = validate_explicit_pause(
                float(
                    match.group(1)
                )
            )

            # ------------------------------------------------
            # TEXT BEFORE PAUSE
            # ------------------------------------------------

            if before_pause:

                segments.append({

                    "speaker": speaker_id,

                    "text": before_pause,

                    "pause_after": pause_value

                })

            else:

                # --------------------------------------------
                # PAUSE WITHOUT TEXT BEFORE IT
                # --------------------------------------------

                if segments:

                    segments[-1]["pause_after"] = (
                        pause_value
                    )

                else:

                    segments.append({

                        "speaker": speaker_id,

                        "text": "",

                        "pause_after": pause_value

                    })

            position = match.end()


        # ----------------------------------------------------
        # TEXT AFTER LAST PAUSE
        # ----------------------------------------------------

        after_pause = (
            text[position:]
            .strip()
        )

        if after_pause:

            segments.append({

                "speaker": speaker_id,

                "text": after_pause,

                "pause_after": None

            })


    # ========================================================
    # MAIN LOOP
    # ========================================================

    for raw_line in lines:

        line = raw_line.strip()

        # ----------------------------------------------------
        # EMPTY LINE
        #
        # لا تعتبر متحدثاً
        # ولا تغير Speaker
        # ----------------------------------------------------

        if not line:

            continue


        # ----------------------------------------------------
        # PAUSE ONLY LINE
        #
        # لا تغير المتحدث
        # ----------------------------------------------------

        pause_only_match = (
            PAUSE_PATTERN.fullmatch(
                line
            )
        )

        if pause_only_match:

            pause_value = validate_explicit_pause(
                float(
                    pause_only_match.group(1)
                )
            )

            # -----------------------------------------------
            # إذا كان هناك Segment سابق
            # نضيف الصمت بعده.
            # -----------------------------------------------

            if segments:

                segments[-1]["pause_after"] = (
                    pause_value
                )

            else:

                # حالة نادرة:
                # PAUSE في بداية السكريبت.

                segments.append({

                    "speaker": current_speaker,

                    "text": "",

                    "pause_after": pause_value

                })

            continue


        # ----------------------------------------------------
        # DIALOGUE LINE
        # ----------------------------------------------------

        process_dialogue_line(

            text=line,

            speaker_id=current_speaker

        )


        # ----------------------------------------------------
        # SWITCH SPEAKER
        #
        # التبديل يحدث فقط بعد سطر حوار كامل.
        #
        # PAUSE لا تغير المتحدث.
        # ----------------------------------------------------

        if current_speaker == 1:

            current_speaker = 2

        else:

            current_speaker = 1


    # ========================================================
    # REMOVE EMPTY TEXT SEGMENTS
    # ========================================================

    cleaned_segments = []

    pending_leading_pause = None

    for segment in segments:

        text = segment["text"].strip()

        pause_after = segment.get(
            "pause_after"
        )

        # ----------------------------------------------------
        # EMPTY SEGMENT
        # ----------------------------------------------------

        if not text:

            if pause_after is not None:

                pending_leading_pause = (
                    pause_after
                )

            continue


        # ----------------------------------------------------
        # NORMAL SEGMENT
        # ----------------------------------------------------

        if (
            pending_leading_pause is not None
            and cleaned_segments
        ):

            cleaned_segments[-1][
                "pause_after"
            ] = pending_leading_pause

            pending_leading_pause = None


        cleaned_segments.append({

            "speaker": segment["speaker"],

            "text": text,

            "pause_after": pause_after

        })


    segments = cleaned_segments


    # ========================================================
    # VALIDATE
    # ========================================================

    if not segments:

        raise ValueError(
            "No valid podcast dialogue lines found."
        )


    return segments


# ============================================================
# REMOVE PAUSE TOKENS
# ============================================================

def clean_pause_tokens(
    text: str
):

    """
    طبقة حماية إضافية.

    حتى لو وصل PAUSE للنص بالخطأ،
    يتم حذفه قبل Edge TTS.
    """

    return PAUSE_PATTERN.sub(
        "",
        text
    ).strip()


# ============================================================
# AUDIO DECODER
# ============================================================

def decode_audio_to_pcm(
    audio_bytes: bytes,
    target_sample_rate: int = 48000
):

    container = None

    try:

        container = av.open(
            io.BytesIO(audio_bytes),
            mode="r"
        )

        stream = (
            container
            .streams
            .audio[0]
        )

        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=target_sample_rate
        )

        pcm_chunks = []

        for frame in container.decode(
            stream
        ):

            converted_frames = (
                resampler.resample(
                    frame
                )
            )

            if not isinstance(
                converted_frames,
                list
            ):

                converted_frames = [
                    converted_frames
                ]

            for converted in converted_frames:

                pcm_chunks.append(
                    converted
                    .to_ndarray()
                    .tobytes()
                )


        # Flush Resampler

        flushed = resampler.resample(
            None
        )

        if flushed:

            if not isinstance(
                flushed,
                list
            ):

                flushed = [
                    flushed
                ]

            for converted in flushed:

                pcm_chunks.append(
                    converted
                    .to_ndarray()
                    .tobytes()
                )


        pcm = b"".join(
            pcm_chunks
        )

        if not pcm:

            raise RuntimeError(
                "Decoded audio is empty."
            )

        return (
            pcm,
            target_sample_rate
        )

    finally:

        if container is not None:

            container.close()


# ============================================================
# SILENCE
# ============================================================

def generate_silence(
    seconds: float,
    sample_rate: int
) -> bytes:

    """
    إنشاء صمت PCM حقيقي.

    الـ PAUSE Token لا يتم نطقه.

    يتم تحويله إلى Samples صامتة.
    """

    seconds = validate_pause(
        seconds
    )

    samples = int(
        seconds * sample_rate
    )

    return (
        b"\x00\x00"
        * samples
    )


# ============================================================
# WAV
# ============================================================

def pcm_to_wav_bytes(
    pcm: bytes,
    sample_rate: int
) -> bytes:

    output = io.BytesIO()

    with wave.open(
        output,
        "wb"
    ) as wav:

        wav.setnchannels(1)

        wav.setsampwidth(2)

        wav.setframerate(
            sample_rate
        )

        wav.writeframes(
            pcm
        )

    return output.getvalue()


# ============================================================
# MP3
# ============================================================

def pcm_to_mp3_bytes(
    pcm: bytes,
    sample_rate: int,
    bitrate: str
) -> bytes:

    output = io.BytesIO()

    container = None

    try:

        container = av.open(
            output,
            mode="w",
            format="mp3"
        )

        stream = container.add_stream(
            "libmp3lame",
            rate=sample_rate
        )

        stream.bit_rate = (

            int(
                bitrate
                .lower()
                .replace(
                    "k",
                    ""
                )
            )

            * 1000
        )

        stream.layout = "mono"


        bytes_per_sample = 2

        samples_per_frame = 1152


        total_samples = (

            len(pcm)

            // bytes_per_sample

        )


        offset = 0


        while offset < total_samples:


            remaining = (

                total_samples

                - offset

            )


            frame_samples = min(

                samples_per_frame,

                remaining

            )


            start = (

                offset

                * bytes_per_sample

            )


            end = (

                start

                + frame_samples

                * bytes_per_sample

            )


            chunk = pcm[
                start:end
            ]


            frame = av.AudioFrame(

                format="s16",

                layout="mono",

                samples=frame_samples

            )


            frame.sample_rate = (
                sample_rate
            )


            frame.planes[0].update(
                chunk
            )


            frame.pts = offset


            for packet in stream.encode(
                frame
            ):

                container.mux(
                    packet
                )


            offset += frame_samples


        for packet in stream.encode():

            container.mux(
                packet
            )


        container.close()

        container = None


        return output.getvalue()


    finally:

        if container is not None:

            container.close()


# ============================================================
# PODCAST ENGINE
# ============================================================

async def build_podcast_audio(

    segments: List[dict],

    speaker_configs: Dict[
        int,
        SpeakerConfig
    ],

    auto_pause: bool,

    auto_pause_duration: float

):

    target_sample_rate = 48000

    final_pcm_parts = []

    previous_speaker = None


    total_segments = len(
        segments
    )


    for index, segment in enumerate(

        segments,

        start=1

    ):


        speaker_id = segment[
            "speaker"
        ]


        # ====================================================
        # SAFETY:
        # REMOVE PAUSE TOKENS BEFORE TTS
        # ====================================================

        text = clean_pause_tokens(
            segment["text"]
        )


        if not text:

            continue


        if speaker_id not in speaker_configs:

            raise ValueError(

                f"Unsupported speaker: "
                f"{speaker_id}"

            )


        config = speaker_configs[
            speaker_id
        ]


        logger.info(

            "Podcast segment %s/%s | "

            "speaker=%s | chars=%s",

            index,

            total_segments,

            speaker_id,

            len(text)

        )


        # ====================================================
        # AUTOMATIC SPEAKER TRANSITION PAUSE
        # ====================================================

        if (

            auto_pause

            and previous_speaker is not None

            and previous_speaker != speaker_id

        ):


            final_pcm_parts.append(

                generate_silence(

                    auto_pause_duration,

                    target_sample_rate

                )

            )


        # ====================================================
        # GENERATE SPEECH
        # ====================================================

        audio_bytes = await generate_tts_file(

            text=text,

            voice=config.voice,

            rate=config.rate,

            pitch=config.pitch

        )


        pcm, sample_rate = (

            decode_audio_to_pcm(

                audio_bytes,

                target_sample_rate

            )

        )


        final_pcm_parts.append(
            pcm
        )


        # ====================================================
        # EXPLICIT PAUSE
        # ====================================================

        explicit_pause = segment.get(
            "pause_after"
        )


        if explicit_pause is not None:


            logger.info(

                "Adding explicit pause: %s seconds",

                explicit_pause

            )


            final_pcm_parts.append(

                generate_silence(

                    explicit_pause,

                    target_sample_rate

                )

            )


        previous_speaker = (
            speaker_id
        )


    final_pcm = b"".join(
        final_pcm_parts
    )


    if not final_pcm:

        raise RuntimeError(
            "Final podcast audio is empty."
        )


    return (

        final_pcm,

        target_sample_rate

    )


# ============================================================
# PODCAST ENDPOINT
# ============================================================

@app.post("/podcast")
async def podcast(
    data: PodcastRequest
):

    if not data.script.strip():

        raise HTTPException(
            status_code=400,
            detail="Podcast script is empty."
        )

    try:

        output_format = validate_format(
            data.format
        )


        bitrate = validate_bitrate(
            data.bitrate
        )


        auto_pause_duration = (
            validate_pause(
                data.auto_pause_duration
            )
        )


        # ====================================================
        # PARSE
        # ====================================================

        segments = parse_podcast_script(
            data.script
        )


        logger.info(

            "Podcast parsed | segments=%s",

            len(segments)

        )


        # ====================================================
        # SPEAKERS
        # ====================================================

        speaker_configs = {

            1: data.speaker1,

            2: data.speaker2

        }


        # ====================================================
        # BUILD
        # ====================================================

        pcm, sample_rate = (

            await build_podcast_audio(

                segments=segments,

                speaker_configs=speaker_configs,

                auto_pause=data.auto_pause,

                auto_pause_duration=(
                    auto_pause_duration
                )

            )

        )


        # ====================================================
        # OUTPUT
        # ====================================================

        if output_format == "wav":


            final_audio = (

                pcm_to_wav_bytes(

                    pcm,

                    sample_rate

                )

            )


            media_type = "audio/wav"

            filename = "podcast.wav"


        else:


            final_audio = (

                pcm_to_mp3_bytes(

                    pcm,

                    sample_rate,

                    bitrate

                )

            )


            media_type = "audio/mpeg"


            filename = (

                f"podcast_{bitrate}.mp3"

            )


        logger.info(
            "Podcast completed successfully."
        )


        return Response(

            content=final_audio,

            media_type=media_type,

            headers={

                "Content-Disposition":

                    f'attachment; filename="{filename}"'

            }

        )


    except ValueError as e:


        raise HTTPException(

            status_code=400,

            detail=str(e)

        )


    except Exception as e:


        logger.exception(
            "Podcast generation failed."
        )


        raise HTTPException(

            status_code=500,

            detail=str(e)

        )


# ============================================================
# VALIDATE PODCAST
# ============================================================

@app.post("/podcast/validate")
async def validate_podcast(
    data: PodcastRequest
):

    try:


        segments = parse_podcast_script(
            data.script
        )


        return {

            "valid": True,


            "characters": len(
                data.script
            ),


            "segments": len(
                segments
            ),


            "speakers": sorted(

                list(

                    set(

                        segment["speaker"]

                        for segment in segments

                    )

                )

            ),


            "preview": segments[:10],


            "podcast_logic": {

                "speaker_labels_required": False,

                "switching_method":
                    "automatic_line_alternation",

                "first_line":
                    "speaker1",

                "second_line":
                    "speaker2",

                "pause_changes_speaker":
                    False

            },


            "pause_standard": [

                0.5,

                0.75,

                1.0,

                1.25,

                1.5,

                1.75,

                2.0,

                2.25,

                2.5,

                3.0

            ]

        }


    except Exception as e:


        raise HTTPException(

            status_code=400,

            detail=str(e)

        )
