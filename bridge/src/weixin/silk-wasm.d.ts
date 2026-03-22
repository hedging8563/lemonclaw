declare module 'silk-wasm' {
  export function decode(
    silk: Uint8Array | Buffer,
    sampleRate: number,
  ): Promise<{ data: Uint8Array; duration: number }>;
}
