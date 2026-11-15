// Speak text chunks ALOUD with an AVSpeechSynthesizer voice and record the Mac's own
// sound output while it does. This is the only way to get a macOS Personal Voice into
// a file: macOS will speak it but will not render it to a buffer.
//
//   swift pv_speak_record.swift personal|<voice name substring> chunks.json outdir
//
// Writes outdir/playback.wav (everything the Mac played) and outdir/marks.json
// ([[start, end], ...] seconds into playback.wav, one pair per chunk).
// Needs: Personal Voice access, and Screen & System Audio Recording permission for the
// app this runs under. Keep the Mac otherwise silent while it runs.
import AVFoundation
import Foundation
import ScreenCaptureKit

func die(_ msg: String, _ code: Int32) -> Never { FileHandle.standardError.write((msg + "\n").data(using: .utf8)!); exit(code) }

let a = CommandLine.arguments
guard a.count == 4 else { die("usage: pv_speak_record.swift personal|<name> chunks.json outdir", 2) }
let query = a[1], outDir = URL(fileURLWithPath: a[3])
let texts = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: a[2]))) as! [String]

final class Recorder: NSObject, SCStreamOutput, SCStreamDelegate {
    let url: URL
    var file: AVAudioFile?
    var firstPTS: Double?
    var frames: Int64 = 0
    let lock = NSLock()
    init(url: URL) { self.url = url }
    func stream(_ stream: SCStream, didOutputSampleBuffer sb: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sb.isValid, let fd = sb.formatDescription,
              let asbd = fd.audioStreamBasicDescription else { return }
        var desc = asbd
        guard let format = AVAudioFormat(streamDescription: &desc) else { return }
        lock.lock(); defer { lock.unlock() }
        do {
            try sb.withAudioBufferList { abl, _ in
                guard let pcm = AVAudioPCMBuffer(pcmFormat: format, bufferListNoCopy: abl.unsafePointer) else { return }
                if file == nil {
                    file = try AVAudioFile(forWriting: url, settings: format.settings,
                                           commonFormat: format.commonFormat, interleaved: format.isInterleaved)
                    firstPTS = sb.presentationTimeStamp.seconds
                }
                try file!.write(from: pcm)
                frames += Int64(pcm.frameLength)
            }
        } catch { FileHandle.standardError.write("audio write error: \(error)\n".data(using: .utf8)!) }
    }
    func stream(_ stream: SCStream, didStopWithError error: Error) {
        FileHandle.standardError.write("capture stopped: \(error)\n".data(using: .utf8)!)
    }
    func close() { lock.lock(); file = nil; lock.unlock() }
}

final class SpeechWaiter: NSObject, AVSpeechSynthesizerDelegate {
    var onFinish: (() -> Void)?
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didFinish u: AVSpeechUtterance) { onFinish?(); onFinish = nil }
    func speechSynthesizer(_ s: AVSpeechSynthesizer, didCancel u: AVSpeechUtterance) { onFinish?(); onFinish = nil }
}

func now() -> Double { CMClockGetTime(CMClockGetHostTimeClock()).seconds }

@MainActor func run() async {
    // voice
    var voice: AVSpeechSynthesisVoice?
    if query == "personal" {
        var st = AVSpeechSynthesizer.personalVoiceAuthorizationStatus
        if st != .authorized {
            st = await withCheckedContinuation { c in AVSpeechSynthesizer.requestPersonalVoiceAuthorization { c.resume(returning: $0) } }
        }
        guard st == .authorized else { die("PERSONAL_VOICE_NOT_AUTHORIZED status=\(st.rawValue)", 3) }
        voice = AVSpeechSynthesisVoice.speechVoices().first { $0.voiceTraits.contains(.isPersonalVoice) }
    } else {
        voice = AVSpeechSynthesisVoice.speechVoices().filter { $0.name.localizedCaseInsensitiveContains(query) }
            .max { $0.quality.rawValue < $1.quality.rawValue }
    }
    guard let v = voice else { die("VOICE_NOT_FOUND \(query)", 4) }
    print("voice: \(v.name)")

    // system-audio capture
    let content: SCShareableContent
    do { content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true) }
    catch { die("SCREEN_AUDIO_CAPTURE_NOT_PERMITTED \(error.localizedDescription)", 5) }
    guard let display = content.displays.first else { die("no display to attach the audio capture to", 6) }
    let cfg = SCStreamConfiguration()
    cfg.capturesAudio = true
    cfg.excludesCurrentProcessAudio = false
    cfg.sampleRate = 48000
    cfg.channelCount = 2
    cfg.width = 2; cfg.height = 2
    cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    let rec = Recorder(url: outDir.appendingPathComponent("playback.wav"))
    let stream = SCStream(filter: SCContentFilter(display: display, excludingApplications: [], exceptingWindows: []),
                          configuration: cfg, delegate: rec)
    do {
        try stream.addStreamOutput(rec, type: .audio, sampleHandlerQueue: DispatchQueue(label: "pv.audio"))
        try await stream.startCapture()
    } catch { die("SCREEN_AUDIO_CAPTURE_NOT_PERMITTED \(error.localizedDescription)", 5) }

    // wait for the first audio buffer so marks have a zero point
    let t0 = Date()
    while rec.firstPTS == nil && Date().timeIntervalSince(t0) < 10 { try? await Task.sleep(nanoseconds: 100_000_000) }
    guard let zero = rec.firstPTS else { die("capture started but delivered no audio", 7) }
    try? await Task.sleep(nanoseconds: 500_000_000)

    let synth = AVSpeechSynthesizer(), waiter = SpeechWaiter()
    synth.delegate = waiter
    var marks: [[Double]] = []
    for (i, text) in texts.enumerated() {
        let utt = AVSpeechUtterance(string: text)
        utt.voice = v
        let s = now() - zero
        await withCheckedContinuation { (c: CheckedContinuation<Void, Never>) in
            waiter.onFinish = { c.resume() }
            synth.speak(utt)
        }
        try? await Task.sleep(nanoseconds: 350_000_000)   // let the tail of the audio reach the capture
        let e = now() - zero
        marks.append([s, e])
        print("chunk \(i): \(String(format: "%.2f", s)) - \(String(format: "%.2f", e))")
        try? await Task.sleep(nanoseconds: 450_000_000)   // clear silence between chunks
    }
    try? await stream.stopCapture()
    rec.close()
    try! JSONSerialization.data(withJSONObject: marks).write(to: outDir.appendingPathComponent("marks.json"))
    print("recorded \(String(format: "%.1f", Double(rec.frames) / 48000)) s")
    exit(0)
}

Task { await run() }
RunLoop.main.run()
