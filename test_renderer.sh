#!/bin/bash
# Safe Renderer Testing Script
# Tests segment-based rendering with memory monitoring

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║   Safe Segment-Based Renderer Testing Script                  ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Test configuration
TEST_NUM=${1:-1}
BACKUP_FILE="configs/autodj.toml.backup"

# Function to print section headers
print_section() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Function to print status messages
print_status() {
    echo -e "${GREEN}✅${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠️${NC}  $1"
}

print_error() {
    echo -e "${RED}❌${NC} $1"
}

# Backup original config
if [ ! -f "$BACKUP_FILE" ]; then
    print_status "Backing up original config: $BACKUP_FILE"
    cp configs/autodj.toml "$BACKUP_FILE"
else
    print_status "Backup already exists: $BACKUP_FILE"
fi

# Select test based on argument
case $TEST_NUM in
    1)
        print_section "TEST 1: SMALL MIX (5-8 tracks, 5 min)"
        print_warning "No segmentation will occur (threshold is >10 tracks)"

        cat > configs/autodj.toml << 'EOF'
config_version = "1.0"

[mix]
target_duration_minutes = 5
max_playlist_tracks = 5
seed_track_path = ""

[constraints]
bpm_tolerance_percent = 4.0
energy_window_size = 3
min_track_duration_seconds = 120
max_repeat_decay_hours = 168

[analysis]
aubio_hop_size = 512
aubio_buf_size = 4096
bpm_search_range = [50, 200]
confidence_threshold = 0.05

[key_detection]
method = "essentia"
window_size = 4096

[render]
output_format = "mp3"
mp3_bitrate = 192
crossfade_duration_seconds = 4.0
time_stretch_quality = "high"
enable_ladspa_eq = false
max_tracks_before_segment = 10
segment_size = 5
enable_progress_display = true
progress_update_interval = 1.0

[system]
library_path = "/music"
playlists_path = "data/playlists"
mixes_path = "data/mixes"
database_path = "data/db/metadata.sqlite"
log_level = "INFO"

[resources]
max_memory_mb = 256
max_cpu_cores = 0.5
max_analyze_time_sec = 30
max_generate_time_sec = 30
max_render_time_sec = 420

[navidrome]
host = "192.168.1.57"
port = 4533
api_path = "/rest"
username = ""
password = ""
connect_timeout_sec = 5
EOF

        print_status "Config loaded for TEST 1"
        echo ""
        echo "Expected Results:"
        echo "  • Render time: 1-2 minutes"
        echo "  • Peak memory: 100-150 MiB"
        echo "  • Output size: 20-30 MB"
        echo "  • No segmentation (too few tracks)"
        ;;

    2)
        print_section "TEST 2: MEDIUM MIX (11-15 tracks, 15 min)"
        print_warning "Segmentation WILL occur (11 > 10 threshold)"

        cat > configs/autodj.toml << 'EOF'
config_version = "1.0"

[mix]
target_duration_minutes = 15
max_playlist_tracks = 12
seed_track_path = ""

[constraints]
bpm_tolerance_percent = 4.0
energy_window_size = 3
min_track_duration_seconds = 120
max_repeat_decay_hours = 168

[analysis]
aubio_hop_size = 512
aubio_buf_size = 4096
bpm_search_range = [50, 200]
confidence_threshold = 0.05

[key_detection]
method = "essentia"
window_size = 4096

[render]
output_format = "mp3"
mp3_bitrate = 192
crossfade_duration_seconds = 4.0
time_stretch_quality = "high"
enable_ladspa_eq = false
max_tracks_before_segment = 10
segment_size = 5
enable_progress_display = true
progress_update_interval = 1.0

[system]
library_path = "/music"
playlists_path = "data/playlists"
mixes_path = "data/mixes"
database_path = "data/db/metadata.sqlite"
log_level = "INFO"

[resources]
max_memory_mb = 256
max_cpu_cores = 0.5
max_analyze_time_sec = 30
max_generate_time_sec = 30
max_render_time_sec = 420

[navidrome]
host = "192.168.1.57"
port = 4533
api_path = "/rest"
username = ""
password = ""
connect_timeout_sec = 5
EOF

        print_status "Config loaded for TEST 2"
        echo ""
        echo "Expected Results:"
        echo "  • Render time: 3-4 minutes"
        echo "  • Peak memory: 150-180 MiB per segment"
        echo "  • Output size: 40-60 MB"
        echo "  • Segmentation: 2-3 segments"
        echo "  • Progress tracker shows segment updates"
        ;;

    3)
        print_section "TEST 3: LARGE MIX (15-20 tracks, 25 min)"
        print_warning "Segmentation WILL occur with memory stress test"

        cat > configs/autodj.toml << 'EOF'
config_version = "1.0"

[mix]
target_duration_minutes = 25
max_playlist_tracks = 18
seed_track_path = ""

[constraints]
bpm_tolerance_percent = 4.0
energy_window_size = 3
min_track_duration_seconds = 120
max_repeat_decay_hours = 168

[analysis]
aubio_hop_size = 512
aubio_buf_size = 4096
bpm_search_range = [50, 200]
confidence_threshold = 0.05

[key_detection]
method = "essentia"
window_size = 4096

[render]
output_format = "mp3"
mp3_bitrate = 192
crossfade_duration_seconds = 4.0
time_stretch_quality = "high"
enable_ladspa_eq = false
max_tracks_before_segment = 10
segment_size = 5
enable_progress_display = true
progress_update_interval = 1.0

[system]
library_path = "/music"
playlists_path = "data/playlists"
mixes_path = "data/mixes"
database_path = "data/db/metadata.sqlite"
log_level = "INFO"

[resources]
max_memory_mb = 256
max_cpu_cores = 0.5
max_analyze_time_sec = 30
max_generate_time_sec = 30
max_render_time_sec = 420

[navidrome]
host = "192.168.1.57"
port = 4533
api_path = "/rest"
username = ""
password = ""
connect_timeout_sec = 5
EOF

        print_status "Config loaded for TEST 3"
        echo ""
        echo "Expected Results:"
        echo "  • Render time: 6-8 minutes"
        echo "  • Peak memory: 150-200 MiB per segment (WATCH CLOSELY!)"
        echo "  • Output size: 80-120 MB"
        echo "  • Segmentation: 3-4 segments"
        echo "  • Real-time progress tracker updates"
        ;;

    *)
        print_error "Invalid test number. Use 1, 2, or 3"
        echo ""
        echo "Usage: ./test_renderer.sh [test_num]"
        echo "  1 = Small mix (5 tracks, no segmentation)"
        echo "  2 = Medium mix (12 tracks, with segmentation)"
        echo "  3 = Large mix (18 tracks, memory stress test)"
        exit 1
        ;;
esac

# Verify config is valid
if [ -f "configs/autodj.toml" ]; then
    print_status "Config file created"
else
    print_error "Failed to create config file"
    exit 1
fi

echo ""
echo "Next steps:"
echo "  1. Open a new terminal for memory monitoring:"
echo "     watch -n 1 'docker stats --no-stream autodj | tail -1'"
echo ""
echo "  2. In this terminal, run:"
echo "     make dev-up"
echo "     make generate"
echo "     make render"
echo ""
print_warning "Monitor memory in the other terminal - stop if it exceeds 400 MiB"
echo ""
