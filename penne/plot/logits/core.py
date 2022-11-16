import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import torch

import penne


###############################################################################
# Create figure
###############################################################################


def from_audio(
    audio,
    sample_rate,
    pitch=None,
    checkpoint=penne.DEFAULT_CHECKPOINT,
    gpu=None):
    """Plot logits with pitch overlay"""
    logits = []

    # Preprocess audio
    iterator = penne.preprocess(
        audio,
        sample_rate,
        batch_size=penne.EVALUATION_BATCH_SIZE)
    for frames, _ in iterator:

        # Copy to device
        frames = frames.to('cpu' if gpu is None else f'cuda:{gpu}')

        # Infer
        logits.append(penne.infer(frames, checkpoint).detach())

    # Concatenate results
    logits = torch.cat(logits, 2)

    # Setup figure
    figure = plt.figure(figsize=(18, 6))

    # Plot logits
    plt.imshow(logits)

    # Maybe plot pitch overlay
    if pitch is not None:

        # Get pitch bins
        bins = penne.convert.frequency_to_bins(pitch)

        # Make pitch contour black
        colormap = matplotlib.colors.LinearSegmentedColormap.from_list(
            'pitchcolor', [None, 'purple'], 256)
        colormap._init()

        # Apply zero alpha to bins without pitch
        alphas = torch.nn.functional.one_hot(bins, penne.PITCH_BINS)
        colormap._lut[:, -1] = alphas

        # Plot pitch overlay
        plt.imshow(bins, cmap=colormap)

    return figure


def from_file(
    audio_file,
    pitch_file=None,
    checkpoint=penne.DEFAULT_CHECKPOINT,
    gpu=None):
    """Plot logits and optional pitch"""
    # Load audio
    audio = penne.load.audio(audio_file)

    # Maybe load pitch
    pitch = np.load(pitch_file)

    # Plot
    return from_audio(audio, penne.SAMPLE_RATE, pitch, checkpoint, gpu)


def from_file_to_file(
    audio_file,
    output_file,
    pitch_file=None,
    checkpoint=penne.DEFAULT_CHECKPOINT,
    gpu=None):
    """Plot pitch and periodicity and save to disk"""
    # Plot
    figure = from_file(audio_file, pitch_file, checkpoint, gpu)

    # Save to disk
    figure.save(output_file, bbox_inches='tight', pad_inches=0)