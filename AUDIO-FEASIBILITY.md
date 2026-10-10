# Audio in Live View and recordings: investigation

Scope: incoming camera microphone audio for listening in Live View and saving
with video, including automatic motion/ring recordings.

## Implemented first stage (October 9, 2026)

The shared audio setting is implemented, off by default, with Primary/Alternate
track selection. Audio-enabled sessions use MSE and remux H.264 plus one AAC
track into the browser stream and saved recordings. `delay_moov` ensures the
AAC initialization metadata is populated before the MP4 header is emitted.
The actual output codecs determine X-Codec and X-Audio; missing tracks
fall back to video. Native WebRTC remains available when audio is disabled.

Live players now have Listen/Mute controls. All saved video players start
muted, share mute/volume choices for the current page, and reset to muted on
view, pagination, filter or browser-page changes. Playback muting does not
affect captured audio.

Offline tests cover real FFmpeg transport-stream remuxing with two distinct
AAC tones, channel selection, codec headers, absent/disabled audio, partial
recordings, automatic recording through the actual server remux invocation,
browser autoplay fallback and page-scoped preferences. Real microphone sound
and perceived A/V synchronization still need a camera test.

The investigation below describes the starting code and future native
WebRTC work; its implementation recommendations are historical.

## Finding

This is feasible with the current Blink connection. Existing local
`direct.log` entries from October 4 and October 9 show two AAC-LC audio tracks
alongside H.264 video: MPEG-TS PIDs 0x101 and 0x102, 16 kHz, mono, about
32 kbit/s each. The bytes already reach the local FFmpeg input through blinkpy.
Which track contains usable microphone sound still needs a real-camera check;
codec metadata alone cannot establish that.

Installed libraries: blinkpy 0.25.9, aiortc 1.15.0, PyAV 17.1.0.

Before this implementation, the application discarded audio at several points:

| Path | Behavior before implementation |
| --- | --- |
| Auto-record and MSE Live View | `serve.py:send_live_mse` uses `-c:v copy -an`. Both the browser and saved MP4 receive that video-only output. |
| MSE codec signaling | `h264_mime_codec_from_moov` reports only the AVC codec. An audio-enabled MP4 also needs its AAC codec advertised to the SourceBuffer. |
| WebRTC Live View | `blink_ts_demux.DemuxeurTSVideo` selects only H.264. `_PisteH264` and SDP negotiation provide one video track. |
| WebRTC recordings | `_demarrer_enregistrement` feeds raw Annex B H.264 to FFmpeg. Audio and the original MPEG-TS audio timestamps are already gone. |
| Live player | Both protocols create muted video elements; there is currently no live speaker/volume control. |

Removing `-an` addresses only the MSE path. WebRTC needs additional work.

## Recommended configuration

Start with one server setting, **Include camera audio in Live View and
recordings**, default off to preserve existing sessions' behavior. It should
apply to future sessions and automatic recordings as well as manual recordings.
Add a speaker/mute control to each live player. Muting playback must not disable
the audio written to disk. Saved clips use their existing volume controls.

If the camera supplies no audio, continue with a playable video-only stream
and show that audio is unavailable. Turning the setting off must produce
video-only recordings rather than just muting the browser.

The app should start live playback muted and offer a click to listen, preserving
reliable playback when browser autoplay policy blocks audible media.

Independent global listening and recording switches could be added later, but
they require separate output selection: MSE currently sends and saves the same
MP4 bytes. A shared inclusion setting plus a local mute control covers the
immediate use case with less pipeline duplication.

## Implementation choices

**First stage: MSE and automatic recordings.** Preserve H.264 and selected AAC
with stream copy, select a single audio track explicitly, advertise both codecs
when present, and add the speaker control and saved setting. The confirmed
AAC-LC format corresponds to `mp4a.40.2`; the actual output tracks must determine
the codec list, including video-only fallback.

A prototype remux command is:

```text
-map 0:v:0 -map 0:a:0? -c:v copy -c:a copy -bsf:a aac_adtstoasc
-f mp4 -movflags frag_keyframe+empty_moov+default_base_moof+delay_moov
```

The optional audio map allows cameras without an audio track. Track zero is a
prototype choice, pending verification of the two real camera tracks.

For an initial complete user feature, audio-enabled live sessions could use
MSE while ordinary sessions keep their selected protocol. That tradeoff must be
visible: this repository adopted WebRTC because it starts faster.

**Second stage: preserve WebRTC startup performance.** Extend the single stream
reader to deliver AAC and H.264, decode/resample AAC into signed 16-bit PCM for
aiortc's Opus encoder, and negotiate an audio receiver. Keep the existing H.264
passthrough. Both tracks need a common camera timestamp origin and playback
buffer so audio does not run ahead of the video.

The browser's current `ontrack` handler replaces its MediaStream on every track;
it must accumulate both tracks and keep first-image detection tied to video.
Audio ending or becoming unavailable should not unnecessarily end good video.

WebRTC recording should preserve the original A/V transport stream into its
recorder or use an equivalent shared packet muxer. Reusing its current raw-H.264
recorder cannot include audio. Starting recording partway through a session
requires program-table/keyframe handling and aligned audio/video timestamps.

No part of this incoming-audio design requires changing
`BlinkLiveStream.auth`, its TLS context, or issuing speaker/talk commands.
The open blinkpy PR #1303 concerns talk-to-camera support and is separate from
the AAC already present in this account's received transport stream.

## Verification completed

A short offline probe used synthetic H.264 plus two mono AAC tracks with the
same 16 kHz / 32 kbit/s audio parameters observed in the logs:

- Remuxed one selected AAC track and video into fragmented MP4 without
  reencoding; both streams decoded successfully (20 video frames and 33 audio
  frames), and the audio was non-silent.
- Confirmed `moov` and `moof` boxes are present.
- Decoded AAC, converted PCM and encoded/decoded 105 Opus packets using the
  installed PyAV/aiortc libraries.
- Repeated optional audio mapping with video-only input; it stayed decodable.

The probe used temporary synthetic media and did not start a camera, record
real microphone audio, alter dependencies, or change application behavior.

Before shipping: verify the correct microphone track on the actual doorbell,
audible playback, A/V synchronization, automatic recording, recording toggled
midstream, reconnects, missing-audio fallback and complete session cleanup.
Synthetic codec success does not establish those camera/browser behaviors.

## Primary references

- [FFmpeg stream selection and optional mapping](https://www.ffmpeg.org/ffmpeg.html#Stream-selection)
- [aiortc media helpers](https://aiortc.readthedocs.io/en/latest/helpers.html)
- [WebRTC audio codecs](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Formats/WebRTC_codecs)
- [Browser autoplay behavior](https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay)
- [blinkpy PR #1303: outgoing/talk audio](https://github.com/fronzbot/blinkpy/pull/1303)
