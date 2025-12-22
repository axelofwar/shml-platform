import { GoogleGenAI, Modality } from "@google/genai";
import { Attachment } from "../types";

// API key management - supports runtime configuration
const getApiKey = (): string => {
  // Priority: localStorage > env var > empty (will fail gracefully)
  const localKey = typeof window !== 'undefined' ? localStorage.getItem('gemini_api_key') : null;
  return localKey || (import.meta as any).env?.VITE_GEMINI_API_KEY || '';
};

// Lazy initialization to support runtime key changes
let _ai: GoogleGenAI | null = null;
const getAI = (): GoogleGenAI => {
  const key = getApiKey();
  if (!key) {
    throw new Error('Gemini API key not configured. Please set your API key in Settings.');
  }
  if (!_ai) {
    _ai = new GoogleGenAI({ apiKey: key });
  }
  return _ai;
};

// Allow resetting the client when API key changes
export const resetAIClient = () => {
  _ai = null;
};

// Helper to prepare parts for the model
const prepareParts = (textQuery: string | null, audioQueryBase64: string | null, attachments: Attachment[]) => {
  const parts: any[] = [];

  // Add attachments (Context)
  attachments.forEach((file) => {
    parts.push({
      inlineData: {
        mimeType: file.type,
        data: file.data,
      },
    });
  });

  // Add User Audio Query
  if (audioQueryBase64) {
    parts.push({
      inlineData: {
        mimeType: "audio/webm;codecs=opus", // Common browser recorder format
        data: audioQueryBase64,
      },
    });
  }

  // Add User Text Query
  if (textQuery) {
    parts.push({ text: textQuery });
  }

  return parts;
};

export const generateAnswer = async (
  textQuery: string | null,
  audioQueryBase64: string | null,
  attachments: Attachment[]
): Promise<string> => {
  try {
    const ai = getAI();
    const parts = prepareParts(textQuery, audioQueryBase64, attachments);

    // Use gemini-2.5-flash for speed and multimodal capabilities
    const response = await ai.models.generateContent({
      model: "gemini-2.5-flash",
      contents: { parts },
      config: {
        systemInstruction: "You are a helpful assistant for the SBA Resource Portal. Answer questions based on the provided PDF and audio files. Be concise, professional, and accurate.",
      },
    });

    return response.text || "I'm sorry, I couldn't generate an answer based on the provided resources.";
  } catch (error) {
    console.error("Error generating answer:", error);
    throw error;
  }
};

// Text-to-Speech Generation
export const generateSpeech = async (text: string): Promise<{ buffer: AudioBuffer, base64: string } | null> => {
  try {
    const ai = getAI();
    const response = await ai.models.generateContent({
      model: "gemini-2.5-flash-preview-tts",
      contents: [{ parts: [{ text }] }],
      config: {
        responseModalities: [Modality.AUDIO],
        speechConfig: {
          voiceConfig: {
            prebuiltVoiceConfig: { voiceName: 'Kore' },
          },
        },
      },
    });

    const base64Audio = response.candidates?.[0]?.content?.parts?.[0]?.inlineData?.data;

    if (!base64Audio) return null;

    const audioContext = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate: 24000 });
    const audioBuffer = await decodeAudioData(decode(base64Audio), audioContext, 24000, 1);

    return { buffer: audioBuffer, base64: base64Audio };
  } catch (error) {
    console.error("Error generating speech:", error);
    return null;
  }
};

// --- Audio Decoding Helpers (from Google GenAI Guidelines) ---

export function decode(base64: string) {
  const binaryString = atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

export async function decodeAudioData(
  data: Uint8Array,
  ctx: AudioContext,
  sampleRate: number,
  numChannels: number,
): Promise<AudioBuffer> {
  const dataInt16 = new Int16Array(data.buffer);
  const frameCount = dataInt16.length / numChannels;
  const buffer = ctx.createBuffer(numChannels, frameCount, sampleRate);

  for (let channel = 0; channel < numChannels; channel++) {
    const channelData = buffer.getChannelData(channel);
    for (let i = 0; i < frameCount; i++) {
      channelData[i] = dataInt16[i * numChannels + channel] / 32768.0;
    }
  }
  return buffer;
}
