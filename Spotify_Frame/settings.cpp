#include "state.h"
#include "config.h"
#include <Preferences.h>

AppState app;
Settings settings;

void Settings::load() {
  Preferences p;
  p.begin("gf", true);
  verseMin = p.getUShort("v_min", DEF_VERSE_MIN);
  idleMin = p.getUShort("i_min", DEF_IDLE_MIN);
  progressS = p.getUShort("p_s", DEF_PROGRESS_S);
  lyricLeadMs = p.getShort("lyr_lead", DEF_LYRIC_LEAD_MS);
  quietStart = p.getUChar("q_s", DEF_QUIET_START);
  quietEnd = p.getUChar("q_e", DEF_QUIET_END);
  lyricsOn = p.getBool("lyr_on", true);
  herName = p.getString("name", HER_NAME);
  p.end();
}

void Settings::save() {
  Preferences p;
  p.begin("gf", false);
  p.putUShort("v_min", verseMin);
  p.putUShort("i_min", idleMin);
  p.putUShort("p_s", progressS);
  p.putShort("lyr_lead", lyricLeadMs);
  p.putUChar("q_s", quietStart);
  p.putUChar("q_e", quietEnd);
  p.putBool("lyr_on", lyricsOn);
  p.putString("name", herName);
  p.end();
}
