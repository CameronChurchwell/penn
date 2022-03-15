"""evaluate.py - model evaluation"""


import argparse
from cgitb import reset
import json
from pathlib import Path
import numpy as np
import torch
import tqdm
import os
import time

import penne


###############################################################################
# Evaluate
###############################################################################


def dataset(name, partition, model, model_name, skip_predictions, ar, device):
    """Evaluate a dataset

    Arguments
        name - string
            The name of the dataset
        partition - string
            The partition to evaluate

    Returns
        results - dict
            The dictionary of results. The key is the name of a metric and
            the value is the value received for that metric. Must be JSON
            serializable.
    """
    # use 1/5 train set for hparam search
    hparam_stems = penne.data.partitions(name)['train']
    hparam_stems = hparam_stems[:len(hparam_stems)//5]
    # Get stems for this partition
    test_stems = penne.data.partitions(name)[partition]

    # Resolve stems to filenames
    # files = [penne.data.stem_to_file(name, stem) for stem in stems]

    # Partition files
    return from_stems(name, model, model_name, skip_predictions, hparam_stems, test_stems, ar, device)


def dataset_to_file(name, partition, model, model_name, skip_predictions, ar, device):
    """Evaluate dataset and write results to json file

    Arguments
        name - string
            The name of the dataset
        partition - string
            The partition to evaluate
        model - NAME.Model
            The model to evaluate
        model_name - string
            The name of model for directory and file naming
    """
    model_eval_dir = penne.EVAL_DIR / name / model_name
    if not os.path.exists(model_eval_dir):
        os.makedirs(model_eval_dir)
    file = model_eval_dir / f'{model_name}_on_{name}.json'
    with open(file, 'w') as file:
        json.dump(dataset(name, partition, model, model_name, skip_predictions, ar, device), file)


def from_stems(name, model, model_name, skip_predictions, hparam_stems, test_stems, ar, device):
    """Evaluate files

    Arguments
        model - penne.Model
            The model to evaluate
        stems - list(string)
            The stems to evaluate

    Returns
        results - dict
            The dictionary of results. The key is the name of a metric and
            the value is the value received for that metric. Must be JSON
            serializable.
    """
    model_eval_dir = penne.EVAL_DIR / name / model_name
    pitch_dir = model_eval_dir / 'pitch'
    periodicity_dir = model_eval_dir / 'periodicity'
    if not os.path.exists(pitch_dir):
        os.makedirs(pitch_dir)
    if not os.path.exists(periodicity_dir):
        os.makedirs(periodicity_dir)

    total_seconds = 0
    total_frames = 0
    total_infers = 0
    if not skip_predictions:
        for stem in tqdm.tqdm((hparam_stems + test_stems), dynamic_ncols=True, desc="Predicting"):
            if ar:
                frames = torch.from_numpy(np.load(penne.data.stem_to_cache_frames(name, stem, False))).to(device)
                frames -= frames.mean(dim=1, keepdim=True)
                frames /= torch.max(torch.tensor(1e-10, device=frames.device),
                    frames.std(dim=1, keepdim=True))
                pitch, pitch_dist, entropies = penne.ar_loop(model, frames, ar_bins=True)
                pitch = penne.convert.bins_to_frequency(pitch.squeeze(0)).cpu()
                periodicity = entropies.cpu()
            else:
                # get audio file path
                audio_file = penne.data.stem_to_file(name, stem)

                # conditionally set fmax
                fmax = 550. if name == 'PTDB' else penne.MAX_FMAX
                
                # get model-predicted pitch
                pitch, periodicity, seconds, infers = penne.predict_from_file(audio_file, model=model, batch_size=1024, return_periodicity=True, return_time=True, device=device, decoder=penne.decode.argmax, fmax=fmax, pad=name!='PTDB')
                total_seconds += seconds
                total_frames += pitch.shape[1]
                total_infers += infers

            np_pitch = pitch.numpy()
            np_periodicity = periodicity.numpy()

            # save prediction as npy
            np.save(pitch_dir / f'{stem}.npy', np_pitch)
            np.save(periodicity_dir / f'{stem}.npy', np_periodicity)


    # setup metrics
    def evaluate_at_threshold(thresh_val, stems):
        print(f'evaluating at {thresh_val}')
        thresh = penne.threshold.At(thresh_val)
        f1 = penne.metrics.F1(thresh)
        wrmse = penne.metrics.WRMSE()
        rpa = penne.metrics.RPA()
        rca = penne.metrics.RCA()
        # loop over stems

        for stem in stems:
            # get annotation file path
            annotation_file = penne.data.stem_to_annotation(name, stem)

            # get annotated pitch
            annotation = penne.load.pitch_annotation(name, annotation_file)
            np_annotation = annotation.numpy()

            # load npy predictions
            np_pitch = np.load(pitch_dir /  f'{stem}.npy')
            np_periodicity = np.load(periodicity_dir / f'{stem}.npy')

            # handle off by one error
            if name == 'PTDB' and np_pitch.shape[1] > np_annotation.shape[1]:
                np_pitch = np_pitch[:,:np_annotation.shape[1]]
                np_periodicity = np_periodicity[:,:np_annotation.shape[1]]
            # update metrics
            f1.update(np_pitch, np_annotation, np_periodicity)
            wrmse.update(np_pitch, np_annotation, np_periodicity)
            rpa.update(np_pitch, np_annotation)
            rca.update(np_pitch, np_annotation)

        # compute final metrics
        precision, recall, f1_val = f1()
        wrmse_val = wrmse()
        rpa_val = rpa()
        rca_val = rca()

        return {'precision': precision, 'recall': recall, 'f1': f1_val, 'wrmse': wrmse_val, 'rpa': rpa_val, 'rca': rca_val, 'seconds': total_seconds, 'frames': total_frames, 'infers': total_infers}
    
    left = 0
    right = 1
    hparam_results = {}
    while right-left > 0.005:
        if left in hparam_results:
            left_f1 = hparam_results[left].get('f1', 0)
        else:
            scores = evaluate_at_threshold(left, hparam_stems)
            hparam_results[left] = scores
            left_f1 = scores['f1']
        if right in hparam_results:
            right_f1 = hparam_results[right].get('f1', 0)
        else:
            scores = evaluate_at_threshold(right, hparam_stems)
            hparam_results[right] = scores
            right_f1 = scores['f1']
        center = (left + right) / 2
        if right_f1 > left_f1:
            left = center
        else:
            right = center

    file = model_eval_dir / f'hparam_{model_name}_on_{name}.json'
    with open(file, 'w') as file:
        json.dump(hparam_results, file)

    best_thresh = max(hparam_results, key=lambda x: hparam_results[x]['f1'])

    def evaluate_per_stem(thresh_val, stems):
        thresh = penne.threshold.At(thresh_val)
        f1 = penne.metrics.F1(thresh)
        wrmse = penne.metrics.WRMSE()
        rpa = penne.metrics.RPA()
        rca = penne.metrics.RCA()

        res = {}

        # loop over stems
        for stem in stems:
            # get annotation file path
            annotation_file = penne.data.stem_to_annotation(name, stem)

            # get annotated pitch
            annotation = penne.load.pitch_annotation(name, annotation_file)
            np_annotation = annotation.numpy()

            # load npy predictions
            np_pitch = np.load(pitch_dir /  f'{stem}.npy')
            np_periodicity = np.load(periodicity_dir / f'{stem}.npy')

            # handle off by one error
            if name == 'PTDB' and np_pitch.shape[1] > np_annotation.shape[1]:
                np_pitch = np_pitch[:,:np_annotation.shape[1]]
                np_periodicity = np_periodicity[:,:np_annotation.shape[1]]
            # update metrics
            f1.update(np_pitch, np_annotation, np_periodicity)
            wrmse.update(np_pitch, np_annotation, np_periodicity)
            rpa.update(np_pitch, np_annotation)
            rca.update(np_pitch, np_annotation)

            # compute final metrics
            precision, recall, f1_val = f1()
            wrmse_val = wrmse()
            rpa_val = rpa()
            rca_val = rca()

            res[stem] = {'precision': precision, 'recall': recall, 'f1': f1_val, 'wrmse': wrmse_val, 'rpa': rpa_val, 'rca': rca_val}

            f1.reset()
            wrmse.reset()
            rpa.reset()
            rca.reset()
        return res

    file = model_eval_dir / f'per_stem_{model_name}_on_{name}.json'
    with open(file, 'w') as file:
        json.dump(evaluate_per_stem(best_thresh, test_stems), file)
    return evaluate_at_threshold(best_thresh, test_stems)


###############################################################################
# Entry point
###############################################################################


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--dataset',
        required=True,
        help='The name of the dataset to evaluate')
    parser.add_argument(
        '--partition',
        help='The partition to evaluate',
        default='test')
    parser.add_argument(
        '--checkpoint',
        type=Path,
        required=True,
        help='The checkpoint file to evaluate')
    parser.add_argument(
        '--model_name',
        type=str,
        required=True,
        help='Name of model for directory naming')
    parser.add_argument(
        '--device',
        default='cuda',
        help='The device to use for evaluation')
    parser.add_argument(
        '--skip_predictions',
        action='store_true',
        help='If true, will try to use existing predictions')
    parser.add_argument(
        '--ar',
        action='store_true',
        help='If present, will use ar-based inference')
    parser.add_argument(
        '--pdc',
        action='store_true',
        help='If present, will use pdc-based inference')

    return parser.parse_args()

def main():
    """Evaluate a model"""
    # Parse command-line arguments
    args = parse_args()

    # Setup model
    if args.ar:
        penne.infer.model = penne.ARModel.load_from_checkpoint(args.checkpoint).to(args.device)
        penne.infer.model.eval()
    elif args.pdc:
        penne.infer.model = penne.PDCModel.load_from_checkpoint(args.checkpoint).to(args.device)
        penne.infer.model.eval()
    else:
        penne.load.model(device=args.device, checkpoint=args.checkpoint)

    # Evaluate
    dataset_to_file(args.dataset, args.partition, penne.infer.model, args.model_name, args.skip_predictions, args.ar, args.device)


if __name__ == '__main__':
    main()
