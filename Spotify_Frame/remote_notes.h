#pragma once
// Remote notes: the frame polls a private ntfy.sh topic so a note can be sent
// from anywhere (not just her Wi-Fi). New notes are handed to the main loop the
// same way the on-device web app does — via app.pending.newNote.

void remoteNotesBegin();
void remoteNotesTick();   // call from loop(); self-throttles its polling
