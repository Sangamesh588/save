/**
 * MediaDownloader Pro Controller - Light Green & Crisp White Theme
 */

let currentMedia = null;
let progressPollTimer = null;
let deferredPwaPrompt = null;

const PLATFORMS = {
    youtube: { icon: 'fa-brands fa-youtube', color: '#ef4444', name: 'YouTube' },
    instagram: { icon: 'fa-brands fa-instagram', color: '#f43f5e', name: 'Instagram' },
    facebook: { icon: 'fa-brands fa-facebook', color: '#3b82f6', name: 'Facebook' },
    tiktok: { icon: 'fa-brands fa-tiktok', color: '#06b6d4', name: 'TikTok' },
    twitter: { icon: 'fa-brands fa-x-twitter', color: '#0f172a', name: 'X / Twitter' },
    soundcloud: { icon: 'fa-brands fa-soundcloud', color: '#f97316', name: 'SoundCloud' },
    generic: { icon: 'fa-solid fa-link', color: '#10b981', name: 'Web Media' }
};

document.addEventListener('DOMContentLoaded', () => {
    localStorage.removeItem('omnisave_theme');
    if ('caches' in window) {
        caches.keys().then(keys => {
            keys.forEach(k => {
                if (k.includes('v1')) caches.delete(k);
            });
        });
    }
    initInputs();
    initPWA();
});

// PWA Setup
function initPWA() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js').catch(err => {
            console.log('SW registration error:', err);
        });
    }

    const installBtn = document.getElementById('pwaInstallBtn');
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPwaPrompt = e;
        if (installBtn) installBtn.style.display = 'inline-flex';
    });

    if (installBtn) {
        installBtn.addEventListener('click', async () => {
            if (deferredPwaPrompt) {
                deferredPwaPrompt.prompt();
                const choice = await deferredPwaPrompt.userChoice;
                if (choice.outcome === 'accepted') {
                    installBtn.style.display = 'none';
                }
                deferredPwaPrompt = null;
            }
        });
    }
}

// Input Handlers
function initInputs() {
    const urlInput = document.getElementById('urlInput');
    const clearBtn = document.getElementById('clearBtn');
    const pasteBtn = document.getElementById('pasteBtn');
    const platformIcon = document.getElementById('platformIcon');

    if (urlInput) {
        urlInput.addEventListener('input', () => {
            const val = urlInput.value.trim();
            clearBtn.style.display = val.length > 0 ? 'inline-block' : 'none';

            const pKey = detectPlatform(val);
            const p = PLATFORMS[pKey] || PLATFORMS.generic;
            platformIcon.className = `${p.icon} input-icon`;
            platformIcon.style.color = p.color;
        });
    }

    if (clearBtn && urlInput) {
        clearBtn.addEventListener('click', () => {
            urlInput.value = '';
            urlInput.dispatchEvent(new Event('input'));
            urlInput.focus();
        });
    }

    if (pasteBtn && urlInput) {
        pasteBtn.addEventListener('click', async () => {
            try {
                const text = await navigator.clipboard.readText();
                if (text && text.trim().length > 0) {
                    urlInput.value = text.trim();
                    urlInput.dispatchEvent(new Event('input'));
                    fetchMediaDetails();
                }
            } catch (_) {
                urlInput.focus();
            }
        });
    }
}

function detectPlatform(url) {
    const u = url.toLowerCase();
    if (u.includes('youtube.com') || u.includes('youtu.be')) return 'youtube';
    if (u.includes('instagram.com')) return 'instagram';
    if (u.includes('facebook.com') || u.includes('fb.watch')) return 'facebook';
    if (u.includes('tiktok.com')) return 'tiktok';
    if (u.includes('twitter.com') || u.includes('x.com')) return 'twitter';
    if (u.includes('soundcloud.com')) return 'soundcloud';
    return 'generic';
}

function isValidHttpUrl(string) {
    try {
        const u = new URL(string);
        return u.protocol === 'http:' || u.protocol === 'https:';
    } catch (_) {
        return false;
    }
}

// Fetch Media Details
async function fetchMediaDetails() {
    const urlInput = document.getElementById('urlInput');
    const url = (urlInput ? urlInput.value : '').trim();

    if (!url || !isValidHttpUrl(url)) {
        showError('Please paste a valid web URL (e.g. https://www.youtube.com/... or Instagram)');
        return;
    }

    hideError();
    setLoading(true);

    try {
        const res = await fetch('/api/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Failed to inspect link.');
        }

        currentMedia = data.data;
        renderMedia(currentMedia);

    } catch (err) {
        showError(err.message || 'Unable to inspect this link. Ensure the video is public.');
    } finally {
        setLoading(false);
    }
}

function setLoading(isLoading) {
    const submitBtn = document.getElementById('submitBtn');
    const label = submitBtn.querySelector('.btn-label');
    const loading = submitBtn.querySelector('.btn-loading');

    if (isLoading) {
        submitBtn.disabled = true;
        label.style.display = 'none';
        loading.style.display = 'inline-flex';
    } else {
        submitBtn.disabled = false;
        label.style.display = 'inline-flex';
        loading.style.display = 'none';
    }
}

function showError(msg) {
    const box = document.getElementById('errorBox');
    const text = document.getElementById('errorMessage');
    if (box && text) {
        text.textContent = msg;
        box.style.display = 'flex';
        box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function hideError() {
    const box = document.getElementById('errorBox');
    if (box) box.style.display = 'none';
}

// Render Media Overview & Options
function renderMedia(media) {
    const mediaSection = document.getElementById('mediaSection');
    const thumb = document.getElementById('mediaThumb');
    const duration = document.getElementById('mediaDurationBadge');
    const platform = document.getElementById('mediaPlatform');
    const title = document.getElementById('mediaTitleText');
    const uploader = document.getElementById('mediaUploader');
    const previewBtn = document.getElementById('togglePreviewBtn');
    const subsStatusBadge = document.getElementById('subsStatusBadge');
    const subtitlesCardDesc = document.getElementById('subtitlesCardDesc');

    thumb.src = media.thumbnail || '';
    duration.textContent = media.duration || '';
    title.textContent = media.title || 'Untitled';
    uploader.textContent = media.uploader || 'Unknown';

    const p = PLATFORMS[media.platform] || PLATFORMS.generic;
    platform.textContent = p.name;

    previewBtn.style.display = media.youtube_id ? 'inline-flex' : 'none';

    // Subtitle badge handling
    if (media.has_subtitles) {
        subsStatusBadge.className = 'subs-indicator-badge available';
        subsStatusBadge.innerHTML = '<i class="fa-solid fa-closed-captioning"></i> Captions Available';
        subtitlesCardDesc.textContent = 'Subtitles and transcripts are available for this video.';
    } else {
        subsStatusBadge.className = 'subs-indicator-badge unavailable';
        subsStatusBadge.innerHTML = '<i class="fa-regular fa-circle-xmark"></i> No Captions';
        subtitlesCardDesc.textContent = 'This specific video does not have uploaded speech subtitles or captions.';
    }

    // Populate Video Table
    renderVideoTable(media.video_options || []);

    // Populate Audio Table
    renderAudioTable(media.audio_options || []);

    // Reset Trimmer
    resetClip();

    mediaSection.style.display = 'block';
    mediaSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ✂️ TRIMMER FUNCTIONS
function toggleTrimmer() {
    const cb = document.getElementById('trimmerActive');
    cb.checked = !cb.checked;
    syncTrimmerUI();
}

function syncTrimmerUI() {
    const cb = document.getElementById('trimmerActive');
    const controls = document.getElementById('trimmerControls');
    controls.style.display = cb.checked ? 'block' : 'none';
}

function setQuickClip(seconds) {
    const cb = document.getElementById('trimmerActive');
    cb.checked = true;
    syncTrimmerUI();

    document.getElementById('trimStart').value = '00:00';
    if (seconds < 60) {
        const s = seconds < 10 ? `0${seconds}` : seconds;
        document.getElementById('trimEnd').value = `00:${s}`;
    } else {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        document.getElementById('trimEnd').value = `0${m}:${s < 10 ? '0' : ''}${s}`;
    }
}

function resetClip() {
    const cb = document.getElementById('trimmerActive');
    if (cb) cb.checked = false;
    syncTrimmerUI();
    const start = document.getElementById('trimStart');
    const end = document.getElementById('trimEnd');
    if (start) start.value = '00:00';
    if (end) end.value = '';
}

// 🖼️ HD THUMBNAIL DOWNLOAD
function downloadHDThumbnail() {
    if (!currentMedia) return;
    const thumbUrl = currentMedia.best_thumbnail || currentMedia.thumbnail;
    if (!thumbUrl) {
        showError('Thumbnail unavailable.');
        return;
    }
    const downloadApi = `/api/thumbnail?url=${encodeURIComponent(thumbUrl)}&title=${encodeURIComponent(currentMedia.title || 'thumbnail')}`;
    const tempLink = document.createElement('a');
    tempLink.href = downloadApi;
    document.body.appendChild(tempLink);
    tempLink.click();
    document.body.removeChild(tempLink);
}

// 📝 SUBTITLES DOWNLOAD (Enhanced & Robust)
async function downloadSubtitles(format) {
    if (!currentMedia) return;

    const noticeEl = document.getElementById('subtitlesNotice');
    const targetBtn = format === 'srt' ? document.getElementById('downloadSrtBtn') : document.getElementById('downloadTxtBtn');
    const origHtml = targetBtn ? targetBtn.innerHTML : '';

    if (targetBtn) {
        targetBtn.disabled = true;
        targetBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Preparing...';
    }
    if (noticeEl) noticeEl.textContent = 'Extracting and formatting captions...';

    try {
        const res = await fetch('/api/subtitles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: currentMedia.webpage_url,
                format: format
            })
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'No subtitles found for this video.');
        }

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const cleanTitle = (currentMedia.title || 'subtitles').replace(/[\\/*?:"<>|]/g, '').slice(0, 50);
        a.download = `${cleanTitle}.${format}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

        if (noticeEl) {
            noticeEl.innerHTML = '<span style="color: #059669; font-weight: 600;"><i class="fa-solid fa-circle-check"></i> Subtitle downloaded successfully!</span>';
        }

    } catch (err) {
        if (noticeEl) {
            noticeEl.innerHTML = `<span style="color: #DC2626;"><i class="fa-solid fa-circle-exclamation"></i> ${err.message}</span>`;
        } else {
            showError(err.message);
        }
    } finally {
        if (targetBtn) {
            targetBtn.disabled = false;
            targetBtn.innerHTML = origHtml;
        }
    }
}

// Embedded YouTube preview toggle
function toggleEmbeddedPreview() {
    const wrapper = document.getElementById('embedPreviewWrapper');
    const container = document.getElementById('iframeContainer');

    if (!currentMedia || !currentMedia.youtube_id) return;

    if (wrapper.style.display === 'none' || !wrapper.style.display) {
        container.innerHTML = `
            <iframe 
                src="https://www.youtube.com/embed/${currentMedia.youtube_id}?autoplay=1" 
                title="Video Preview" 
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                allowfullscreen>
            </iframe>
        `;
        wrapper.style.display = 'block';
    } else {
        container.innerHTML = '';
        wrapper.style.display = 'none';
    }
}

// Tabs
function selectTab(tab) {
    const tabVideo = document.getElementById('tabVideo');
    const tabAudio = document.getElementById('tabAudio');
    const tabSubtitles = document.getElementById('tabSubtitles');
    const videoPanel = document.getElementById('videoTabPanel');
    const audioPanel = document.getElementById('audioTabPanel');
    const subtitlesPanel = document.getElementById('subtitlesTabPanel');

    tabVideo.classList.remove('active');
    tabAudio.classList.remove('active');
    tabSubtitles.classList.remove('active');
    videoPanel.style.display = 'none';
    audioPanel.style.display = 'none';
    subtitlesPanel.style.display = 'none';

    if (tab === 'video') {
        tabVideo.classList.add('active');
        videoPanel.style.display = 'block';
    } else if (tab === 'audio') {
        tabAudio.classList.add('active');
        audioPanel.style.display = 'block';
    } else if (tab === 'subtitles') {
        tabSubtitles.classList.add('active');
        subtitlesPanel.style.display = 'block';
    }
}

function renderVideoTable(options) {
    const tbody = document.getElementById('videoOptionsBody');
    tbody.innerHTML = '';

    options.forEach(opt => {
        const tr = document.createElement('tr');
        const isRec = opt.recommended ? '<span class="rec-tag">Recommended</span>' : '';

        tr.innerHTML = `
            <td><strong>${opt.label}</strong> ${isRec}</td>
            <td>MP4 Video</td>
            <td>${opt.filesize || 'Auto'}</td>
            <td>
                <button type="button" class="btn-table-action" onclick="startDownloadJob('video', '${opt.height || '0'}', 'mp4')">
                    <i class="fa-solid fa-download"></i> Download
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function renderAudioTable(options) {
    const tbody = document.getElementById('audioOptionsBody');
    tbody.innerHTML = '';

    options.forEach(opt => {
        const tr = document.createElement('tr');
        const isRec = opt.recommended ? '<span class="rec-tag">Recommended</span>' : '';

        tr.innerHTML = `
            <td><strong>${opt.label}</strong> ${isRec}</td>
            <td>${opt.format.toUpperCase()}</td>
            <td><i class="fa-solid fa-compact-disc" style="color: #10B981;"></i> Auto ID3 Album Art Tagged</td>
            <td>
                <button type="button" class="btn-table-action" onclick="startDownloadJob('audio', '${opt.quality}', '${opt.format}')">
                    <i class="fa-solid fa-download"></i> Download ${opt.format.toUpperCase()}
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// Download Trigger & Progress Tracking
async function startDownloadJob(type, quality, format) {
    if (!currentMedia) return;

    // Check if trimmer is active
    const trimmerActive = document.getElementById('trimmerActive').checked;
    const startTime = trimmerActive ? document.getElementById('trimStart').value.trim() : null;
    const endTime = trimmerActive ? document.getElementById('trimEnd').value.trim() : null;

    let displayTitle = currentMedia.title;
    if (trimmerActive && startTime) {
        displayTitle += ` [Clip ${startTime} - ${endTime || 'end'}]`;
    }

    openProgressModal(displayTitle, type, format);

    try {
        const res = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: currentMedia.webpage_url,
                type: type,
                quality: quality,
                audio_format: format,
                start_time: startTime,
                end_time: endTime
            })
        });

        const data = await res.json();
        if (!res.ok || !data.success) {
            throw new Error(data.error || 'Failed to start download job.');
        }

        const jobId = data.job_id;
        trackProgress(jobId, type);

    } catch (err) {
        updateProgressStatus('Error: ' + err.message);
    }
}

function openProgressModal(title, type, format) {
    const modal = document.getElementById('progressModal');
    const filename = document.getElementById('modalFileName');
    const fill = document.getElementById('progressBarFill');
    const percent = document.getElementById('progressPercent');
    const speed = document.getElementById('progressSpeed');
    const statusMsg = document.getElementById('progressStatusMsg');

    filename.textContent = `${title} (${type.toUpperCase()} - ${format.toUpperCase()})`;
    fill.style.width = '10%';
    percent.textContent = '10%';
    speed.textContent = '';
    statusMsg.textContent = 'Connecting and extracting multimedia stream...';

    modal.style.display = 'flex';
}

function closeProgressModal() {
    const modal = document.getElementById('progressModal');
    if (modal) modal.style.display = 'none';
    if (progressPollTimer) {
        clearInterval(progressPollTimer);
        progressPollTimer = null;
    }
}

function updateProgressStatus(msg) {
    const statusMsg = document.getElementById('progressStatusMsg');
    if (statusMsg) statusMsg.textContent = msg;
}

function trackProgress(jobId, mediaType) {
    if (progressPollTimer) clearInterval(progressPollTimer);

    progressPollTimer = setInterval(async () => {
        try {
            const res = await fetch(`/api/progress/${jobId}`);
            const data = await res.json();

            if (!res.ok || !data.success) {
                clearInterval(progressPollTimer);
                updateProgressStatus(data.error || 'Job tracking error.');
                return;
            }

            const job = data.job;
            const fill = document.getElementById('progressBarFill');
            const percent = document.getElementById('progressPercent');
            const speed = document.getElementById('progressSpeed');
            const statusMsg = document.getElementById('progressStatusMsg');

            const p = job.progress || 0;
            fill.style.width = `${p}%`;
            percent.textContent = `${p}%`;

            if (job.speed) speed.textContent = `${job.speed} ${job.eta ? '• ETA: ' + job.eta : ''}`;
            if (job.status_text) statusMsg.textContent = job.status_text;

            if (job.status === 'ready') {
                clearInterval(progressPollTimer);
                fill.style.width = '100%';
                percent.textContent = '100%';
                statusMsg.textContent = 'Completed!';

                setTimeout(() => {
                    closeProgressModal();
                    displayWatchPlayer(jobId, job, mediaType);
                }, 500);

            } else if (job.status === 'error') {
                clearInterval(progressPollTimer);
                updateProgressStatus('Download Error: ' + (job.error || 'Unknown error occurred'));
            }

        } catch (e) {
            console.error('Progress check failed:', e);
        }
    }, 700);
}

// In-Browser Media Player with Auto-Save
function displayWatchPlayer(jobId, job, mediaType) {
    const watchSection = document.getElementById('watchSection');
    const playerTitle = document.getElementById('playerTitle');
    const playerFileSize = document.getElementById('playerFileSize');
    const videoContainer = document.getElementById('videoPlayerContainer');
    const mainVideoPlayer = document.getElementById('mainVideoPlayer');
    const audioContainer = document.getElementById('audioPlayerContainer');
    const mainAudioPlayer = document.getElementById('mainAudioPlayer');
    const audioTrackTitle = document.getElementById('audioTrackTitle');
    const audioPlayerThumb = document.getElementById('audioPlayerThumb');
    const saveFileBtn = document.getElementById('saveFileBtn');

    playerTitle.textContent = job.filename || 'Downloaded Media';
    playerFileSize.textContent = job.filesize_formatted || 'Ready';

    const streamUrl = `/api/stream/${jobId}`;
    const downloadUrl = `/api/file/${jobId}`;

    saveFileBtn.href = downloadUrl;
    saveFileBtn.setAttribute('download', job.filename || 'download');

    if (mediaType === 'audio') {
        videoContainer.style.display = 'none';
        mainVideoPlayer.pause();
        mainVideoPlayer.src = '';

        audioTrackTitle.textContent = job.filename || 'Audio Track';
        audioPlayerThumb.src = currentMedia ? currentMedia.thumbnail : '';
        mainAudioPlayer.src = streamUrl;
        audioContainer.style.display = 'block';
        mainAudioPlayer.load();
        mainAudioPlayer.play().catch(() => {});
    } else {
        audioContainer.style.display = 'none';
        mainAudioPlayer.pause();
        mainAudioPlayer.src = '';

        mainVideoPlayer.src = streamUrl;
        videoContainer.style.display = 'flex';
        mainVideoPlayer.load();
        mainVideoPlayer.play().catch(() => {});
    }

    watchSection.style.display = 'block';
    watchSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    // Also auto-trigger native file save
    const tempLink = document.createElement('a');
    tempLink.href = downloadUrl;
    tempLink.setAttribute('download', job.filename || 'download');
    document.body.appendChild(tempLink);
    tempLink.click();
    document.body.removeChild(tempLink);
}

function scrollToOptions() {
    const mediaSection = document.getElementById('mediaSection');
    if (mediaSection) {
        mediaSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}
