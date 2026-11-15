// Render text chunks to WAV files with an AVSpeechSynthesizer voice, including a
// macOS Personal Voice (which the `say` command cannot use).
//   swift pv_say.swift personal|<voice name substring> chunks.json outdir
// chunks.json: ["first chunk", "second chunk", ...]  ->  outdir/chunk000.wav ...
import AVFoundation
import Foundation

let a = CommandLine.arguments
guard a.count == 4 else { FileHandle.standardError.write("usage: pv_say.swift personal|<name> chunks.json outdir\n".data(using: .utf8)!); exit(2) }
let query = a[1], outDir = URL(fileURLWithPath: a[3])
let texts = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: a[2]))) as! [String]

var voice: AVSpeechSynthesisVoice?
if query == "personal" {
    var st = AVSpeechSynthesizer.personalVoiceAuthorizationStatus
    if st != .authorized {
        // The reply can arrive on the main queue, so keep the run loop turning while we wait.
        var answered = false
        AVSpeechSynthesizer.requestPersonalVoiceAuthorization { s in st = s; answered = true }
        let until = Date().addingTimeInterval(120)
        while !answered && Date() < until { RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.1)) }
        if !answered { st = AVSpeechSynthesizer.personalVoiceAuthorizationStatus }
    }
    guard st == .authorized else {
        FileHandle.standardError.write("PERSONAL_VOICE_NOT_AUTHORIZED status=\(st.rawValue)\n".data(using: .utf8)!); exit(3)
    }
    voice = AVSpeechSynthesisVoice.speechVoices().first { $0.voiceTraits.contains(.isPersonalVoice) }
} else {
    let all = AVSpeechSynthesisVoice.speechVoices().filter { $0.name.localizedCaseInsensitiveContains(query) }
    voice = all.max { $0.quality.rawValue < $1.quality.rawValue }
}
guard let v = voice else { FileHandle.standardError.write("VOICE_NOT_FOUND \(query)\n".data(using: .utf8)!); exit(4) }
print("voice: \(v.name) [\(v.identifier)]")

let synth = AVSpeechSynthesizer()
for (i, text) in texts.enumerated() {
    let utt = AVSpeechUtterance(string: text)
    utt.voice = v
    let url = outDir.appendingPathComponent(String(format: "chunk%03d.wav", i))
    var file: AVAudioFile?
    var done = false
    synth.write(utt) { buf in
        guard let pcm = buf as? AVAudioPCMBuffer else { return }
        if pcm.frameLength == 0 { done = true; return }
        do {
            if file == nil {
                file = try AVAudioFile(forWriting: url, settings: pcm.format.settings,
                                       commonFormat: pcm.format.commonFormat, interleaved: pcm.format.isInterleaved)
            }
            try file!.write(from: pcm)
        } catch { FileHandle.standardError.write("write error: \(error)\n".data(using: .utf8)!); done = true }
    }
    let deadline = Date().addingTimeInterval(120)
    while !done && Date() < deadline { RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.05)) }
    file = nil
    print("chunk \(i): \(done ? "ok" : "TIMEOUT")")
}
