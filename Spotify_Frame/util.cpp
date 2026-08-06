#include "util.h"

String utf8ToLatin1(const String& in) {
  String out;
  out.reserve(in.length());
  const uint8_t* s = (const uint8_t*)in.c_str();
  size_t n = in.length();
  for (size_t i = 0; i < n;) {
    uint8_t c = s[i];
    if (c < 0x80) { out += (char)c; i++; }
    else if ((c == 0xC2 || c == 0xC3) && i + 1 < n) {        // Latin-1 range
      out += (char)(((c & 0x03) << 6) | (s[i + 1] & 0x3F));
      i += 2;
    } else if (c == 0xE2 && i + 2 < n) {                     // punctuation
      uint32_t tri = ((uint32_t)s[i + 1] << 8) | s[i + 2];
      switch (tri) {
        case 0x8098: case 0x8099: case 0x80B2: out += '\''; break;
        case 0x809C: case 0x809D: out += '"'; break;
        case 0x8093: case 0x8094: case 0x8090: out += '-'; break;
        case 0x80A6: out += "..."; break;
        case 0x80A2: out += '-'; break;   // bullet
        default: break;                   // drop
      }
      i += 3;
    } else if ((c & 0xE0) == 0xC0) i += 2;  // other 2-byte: drop
    else if ((c & 0xF0) == 0xE0) i += 3;    // 3-byte: drop
    else if ((c & 0xF8) == 0xF0) i += 4;    // 4-byte (emoji): drop
    else i++;
  }
  return out;
}

String mmss(long ms) {
  long s = ms / 1000;
  char b[12];
  snprintf(b, sizeof(b), "%ld:%02ld", s / 60, s % 60);
  return String(b);
}
