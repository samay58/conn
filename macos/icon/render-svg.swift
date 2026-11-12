// Renders an SVG to a PNG with its transparency intact. Quick Look's
// thumbnailer (the old route) paints transparent areas white, which is where
// the old icon's white border came from.
// Usage: swift render-svg.swift in.svg out.png [size]
import AppKit

let args = CommandLine.arguments
guard args.count >= 3, let image = NSImage(contentsOfFile: args[1]) else {
    FileHandle.standardError.write("usage: render-svg.swift in.svg out.png [size]\n".data(using: .utf8)!)
    exit(1)
}
let size = args.count > 3 ? Int(args[3]) ?? 1024 : 1024
guard let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8,
    samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB,
    bytesPerRow: 0, bitsPerPixel: 0)
else { exit(1) }
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
NSGraphicsContext.current?.imageInterpolation = .high
NSColor.clear.set()
NSRect(x: 0, y: 0, width: size, height: size).fill()
image.draw(in: NSRect(x: 0, y: 0, width: size, height: size))
NSGraphicsContext.restoreGraphicsState()
guard let png = rep.representation(using: .png, properties: [:]) else { exit(1) }
try png.write(to: URL(fileURLWithPath: args[2]))
