# Local interviewer voice

LearnFlow can generate interviewer question audio on its own server with Kokoro
ONNX. This option has no per-request voice API fee. It uses the server's existing
CPU, memory, storage, and hosting allowance.

## How it works

1. The interview service creates and stores the next interviewer question.
2. The signed-in browser requests `POST /interview/{interview_id}/speech`.
3. The API verifies that the interview belongs to that user and selects the
   latest stored interviewer question. Client-provided text is never synthesized.
4. Kokoro creates a WAV file locally in a worker thread.
5. The browser plays the WAV. If local speech is unavailable, LearnFlow falls
   back to the browser voice and the written question remains usable.

Answer transcription is unchanged: the browser creates an editable transcript,
and only that text is submitted to the existing interview response endpoint.
LearnFlow does not store the microphone recording.

## Enable it

Install the backend requirements, then place compatible Kokoro v1.0 ONNX model
and `voices-v1.0.bin` files in an untracked server model directory. The quantized
model is recommended for a CPU-only VM.

Set these deployment secrets or environment values:

```dotenv
LEARNFLOW_INTERVIEW_TTS_PROVIDER=local_kokoro
LEARNFLOW_KOKORO_MODEL_PATH=/opt/learnflow/backend/data/models/kokoro-v1.0.int8.onnx
LEARNFLOW_KOKORO_VOICES_PATH=/opt/learnflow/backend/data/models/voices-v1.0.bin
LEARNFLOW_KOKORO_VOICE=af_heart
LEARNFLOW_KOKORO_LANGUAGE=en-us
LEARNFLOW_KOKORO_SPEED=1.08
LEARNFLOW_MIN_INTERVIEW_TTS_FREE_MB=768
```

Keep the default `LEARNFLOW_INTERVIEW_TTS_PROVIDER=browser` until both model
files and the updated Python requirements are installed. Model binaries must not
be committed to Git.

After changing the deployment environment, restart the API service. The first
audio request loads the model lazily; later requests reuse it. If the memory guard
fails, the UI continues with its safe fallback instead of breaking the interview.
