#pragma once
#include <Arduino.h>

// UTF-8 -> Latin-1 (our fonts cover 32..255); smart quotes/dashes mapped,
// anything unmappable dropped.
String utf8ToLatin1(const String& in);

String mmss(long ms);
