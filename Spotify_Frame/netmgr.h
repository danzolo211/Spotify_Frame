#pragma once
#include <Arduino.h>

bool netConnect();     // saved creds first, then secrets.h; 20s timeout
void netPortal();      // blocking captive-portal setup; restarts on save
void netTimeMdns();    // NTP (timezone from config.h) + graceframe.local
void netReannounce();  // re-publish graceframe.local after a Wi-Fi reconnect
void netForgetWifi();  // clear saved Wi-Fi + arm the setup portal for next boot
