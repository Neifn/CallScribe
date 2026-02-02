# BlackHole Audio Setup Guide

This guide will help you set up BlackHole to capture audio from Chrome browser calls.

## Step 1: Install BlackHole

Open Terminal and run:

```bash
brew install blackhole-2ch
```

After installation, you may need to restart your Mac or log out/in.

## Step 2: Create Multi-Output Device

This allows you to hear audio AND capture it simultaneously.

1. Open **Audio MIDI Setup** (press `Cmd+Space`, type "Audio MIDI Setup")

2. Click the **+** button in the bottom-left corner

3. Select **Create Multi-Output Device**

4. In the right panel, check these boxes:
   - ✅ **BlackHole 2ch**
   - ✅ **MacBook Pro Speakers** (or your headphones)

5. Make sure your speakers/headphones are listed FIRST (drag to reorder if needed)

6. Check **Drift Correction** for BlackHole

7. (Optional) Double-click "Multi-Output Device" to rename it to "Browser Audio Capture"

## Step 3: Set System Audio Output

1. Click the **Apple menu** → **System Settings** → **Sound**

2. Under **Output**, select your new **Multi-Output Device**

Now all system audio will be routed to both:
- Your speakers/headphones (so you can hear it)
- BlackHole (so the app can capture it)

## Step 4: Verify Setup

1. Start the transcription app:
   ```bash
   cd /Users/oleksandrshakhmatov/personal/random/speach-to-text
   source venv/bin/activate
   python -m uvicorn app.main:app
   ```

2. Open http://localhost:8000

3. You should see "BlackHole 2ch" in the device dropdown

4. Play a YouTube video or join a test call

5. Click **Start** - you should see transcription appear!

## Reverting Audio Settings

When you're done transcribing, change your audio output back:

1. **System Settings** → **Sound** → **Output**
2. Select your normal speakers/headphones

## Troubleshooting

### "BlackHole not found"
- Make sure you installed with `brew install blackhole-2ch`
- Try logging out and back in
- Check System Settings → Privacy & Security for any blocked extensions

### No audio being captured
- Verify your system output is set to the Multi-Output Device
- Make sure Chrome is playing audio
- Try increasing the system volume

### Can't hear audio
- In Audio MIDI Setup, ensure your speakers are checked in the Multi-Output Device
- Make sure speakers are listed before BlackHole
