import AppKit
import Foundation
import Vision

struct RecognizedText: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

guard CommandLine.arguments.count >= 2 else {
    FileHandle.standardError.write(Data("usage: room_label_ocr.swift <image>\n".utf8))
    exit(2)
}

let imagePath = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: imagePath) else {
    FileHandle.standardError.write(Data("cannot read image: \(imagePath)\n".utf8))
    exit(3)
}

var proposedRect = NSRect(origin: .zero, size: image.size)
guard let cgImage = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
    FileHandle.standardError.write(Data("cannot create CGImage\n".utf8))
    exit(4)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
let requestedLanguages = ["ko-KR", "en-US"]
if let supportedLanguages = try? request.supportedRecognitionLanguages() {
    let usableLanguages = requestedLanguages.filter { supportedLanguages.contains($0) }
    if !usableLanguages.isEmpty {
        request.recognitionLanguages = usableLanguages
    }
}
request.minimumTextHeight = 0.007
request.customWords = [
    "욕실", "화장실", "주방", "식당", "주방/식당", "거실", "침실",
    "현관", "발코니", "드레스룸", "알파룸", "다용도실", "세탁실",
    "팬트리", "창고", "서재", "복도"
]

let handler = VNImageRequestHandler(cgImage: cgImage, orientation: .up, options: [:])
do {
    try handler.perform([request])
} catch {
    FileHandle.standardError.write(Data("Vision OCR failed: \(error)\n".utf8))
    exit(5)
}

let observations = request.results ?? []
let output: [RecognizedText] = observations.compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let box = observation.boundingBox
    // Vision은 좌하단 원점 정규화 좌표를 사용한다. Python/브라우저가 쓰는
    // 좌상단 원점 좌표로 y만 뒤집어서 전달한다.
    return RecognizedText(
        text: candidate.string,
        confidence: candidate.confidence,
        x: box.minX,
        y: 1.0 - box.maxY,
        width: box.width,
        height: box.height
    )
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.withoutEscapingSlashes]
let encoded = try encoder.encode(output)
FileHandle.standardOutput.write(encoded)
FileHandle.standardOutput.write(Data("\n".utf8))
