import numpy as np
import os
import torch

import config
from utils.eval_utils import procrustes_analysis_batch, scale_and_translation_transform_batch
from utils.local_shape_utils import add_symmetric_measurements, remove_symmetric_measurements_torch, get_measurements_from_vertices


class EvalMetricsTracker:
    """
    Tracks metrics during evaluation.
    """
    def __init__(self, metrics_to_track, img_wh=None, save_path=None,
                 save_per_frame_metrics=False):

        self.metrics_to_track = metrics_to_track
        self.img_wh = img_wh

        self.metric_sums = None
        self.total_samples = 0
        self.save_per_frame_metrics = save_per_frame_metrics
        self.save_path = save_path
        print('\nInitialised metrics tracker.')

    def initialise_metric_sums(self):
        self.metric_sums = {}
        for metric_type in self.metrics_to_track:
            if metric_type == 'silhouette_ious':
                self.metric_sums['num_true_positives'] = 0.
                self.metric_sums['num_false_positives'] = 0.
                self.metric_sums['num_true_negatives'] = 0.
                self.metric_sums['num_false_negatives'] = 0.
            elif metric_type == 'silhouettesamples_ious':
                self.metric_sums['num_samples_true_positives'] = 0.
                self.metric_sums['num_samples_false_positives'] = 0.
                self.metric_sums['num_samples_true_negatives'] = 0.
                self.metric_sums['num_samples_false_negatives'] = 0.
            elif metric_type == 'joints2Dsamples_l2es':
                self.metric_sums['num_vis_joints2Dsamples'] = 0.
                self.metric_sums[metric_type] = 0.
            elif metric_type == 'measurements_mae':
                for measure in config.METAIL_MEASUREMENTS:
                    self.metric_sums[measure] = 0.
            elif metric_type == 'smpl_measurements_mae':
                for measure in config.ALL_MEAS_NAMES_NO_SYMM:
                    self.metric_sums[measure] = 0.
                self.metric_sums['smpl_meas_error_all'] = 0.
            else:
                self.metric_sums[metric_type] = 0.

    def initialise_per_frame_metric_lists(self):
        self.per_frame_metrics = {}
        for metric_type in self.metrics_to_track:
            self.per_frame_metrics[metric_type] = []

    def update_per_batch(self,
                         pred_dict,
                         target_dict,
                         num_input_samples,
                         return_transformed_points=False,
                         return_per_frame_metrics=False):
        self.total_samples += num_input_samples

        if return_transformed_points:
            transformed_points_return_dict = {}
        else:
            transformed_points_return_dict = None
        if return_per_frame_metrics:
            per_frame_metrics_return_dict = {}
        else:
            per_frame_metrics_return_dict = None

        # -------- Update metrics sums --------
        if 'pves' in self.metrics_to_track:
            pve_batch = np.linalg.norm(pred_dict['verts'] - target_dict['verts'], axis=-1)  # (bsize, 6890) or (num views, 6890)
            self.metric_sums['pves'] += np.sum(pve_batch)  # scalar
            self.per_frame_metrics['pves'].append(np.mean(pve_batch, axis=-1))  # (bs,) or (num views,)
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['pves'] = np.mean(pve_batch, axis=-1)

        # Scale and translation correction
        if 'pves_sc' in self.metrics_to_track:
            pred_vertices = pred_dict['verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            target_vertices = target_dict['verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            pred_vertices_sc = scale_and_translation_transform_batch(pred_vertices, target_vertices)
            pve_sc_batch = np.linalg.norm(pred_vertices_sc - target_vertices, axis=-1)  # (bs, 6890) or (num views, 6890)
            self.metric_sums['pves_sc'] += np.sum(pve_sc_batch)  # scalar
            self.per_frame_metrics['pves_sc'].append(np.mean(pve_sc_batch, axis=-1))  # (bs,) or (num views,)
            if return_transformed_points:
                transformed_points_return_dict['pred_vertices_sc'] = pred_vertices_sc
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['pves_sc'] = np.mean(pve_sc_batch, axis=-1)

        # Procrustes analysis
        if 'pves_pa' in self.metrics_to_track:
            pred_vertices = pred_dict['verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            target_vertices = target_dict['verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            pred_vertices_pa = procrustes_analysis_batch(pred_vertices, target_vertices)
            pve_pa_batch = np.linalg.norm(pred_vertices_pa - target_vertices, axis=-1)  # (bsize, 6890) or (num views, 6890)
            self.metric_sums['pves_pa'] += np.sum(pve_pa_batch)  # scalar
            self.per_frame_metrics['pves_pa'].append(np.mean(pve_pa_batch, axis=-1))  # (bs,) or (num views,)
            if return_transformed_points:
                transformed_points_return_dict['pred_vertices_pa'] = pred_vertices_pa
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['pves_pa'] = np.mean(pve_pa_batch, axis=-1)

        # Reposed
        if 'pve-ts' in self.metrics_to_track:
            pvet_batch = np.linalg.norm(pred_dict['reposed_verts'] - target_dict['reposed_verts'], axis=-1)  # (bsize, 6890) or (num views, 6890)
            self.metric_sums['pve-ts'] += np.sum(pvet_batch)  # scalar
            self.per_frame_metrics['pve-ts'].append(np.mean(pvet_batch, axis=-1))  # (bs,)
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['pve-ts'] = np.mean(pvet_batch, axis=-1)

        # Reposed + Scale and translation correction
        if 'pve-ts_sc' in self.metrics_to_track:
            pred_reposed_vertices = pred_dict['reposed_verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            target_reposed_vertices = target_dict['reposed_verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            pred_reposed_vertices_sc = scale_and_translation_transform_batch(pred_reposed_vertices,
                                                                             target_reposed_vertices)
            pvet_sc_batch = np.linalg.norm(pred_reposed_vertices_sc - target_reposed_vertices, axis=-1)  # (bs, 6890) or (num views, 6890)
            self.metric_sums['pve-ts_sc'] += np.sum(pvet_sc_batch)  # scalar
            self.per_frame_metrics['pve-ts_sc'].append(np.mean(pvet_sc_batch, axis=-1))  # (bs,) or (num views,)
            if return_transformed_points:
                transformed_points_return_dict['pred_reposed_vertices_sc'] = pred_reposed_vertices_sc
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['pve-ts_sc'] = np.mean(pvet_sc_batch, axis=-1)

        # Reposed + Procrustes analysis - this doesn't make practical sense for reposed.
        if 'pve-ts_pa' in self.metrics_to_track:
            pred_reposed_vertices = pred_dict['reposed_verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            target_reposed_vertices = target_dict['reposed_verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            pred_reposed_vertices_pa = procrustes_analysis_batch(pred_reposed_vertices,
                                                                 target_reposed_vertices)
            pvet_pa_batch = np.linalg.norm(pred_reposed_vertices_pa - target_reposed_vertices, axis=-1)  # (bsize, 6890) or (num views, 6890)
            self.metric_sums['pve-ts_pa'] += np.sum(pvet_pa_batch)  # scalar
            self.per_frame_metrics['pve-ts_pa'].append(np.mean(pvet_pa_batch, axis=-1))  # (bs,)
            if return_transformed_points:
                transformed_points_return_dict['pred_reposed_vertices_pa'] = pred_reposed_vertices_pa

        if 'mpjpes' in self.metrics_to_track:
            mpjpe_batch = np.linalg.norm(pred_dict['joints3D'] - target_dict['joints3D'], axis=-1)  # (bsize, 14) or (num views, 14)
            self.metric_sums['mpjpes'] += np.sum(mpjpe_batch)  # scalar
            self.per_frame_metrics['mpjpes'].append(np.mean(mpjpe_batch, axis=-1))  # (bs,) or (num views,)
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['mpjpes'] = np.mean(mpjpe_batch, axis=-1)

        # Scale and translation correction
        if 'mpjpes_sc' in self.metrics_to_track:
            pred_joints3D_h36mlsp = pred_dict['joints3D']  # (bsize, 14, 3) or (num views, 14, 3)
            target_joints3D_h36mlsp = target_dict['joints3D']  # (bsize, 14, 3) or (num views, 14, 3)
            pred_joints3D_h36mlsp_sc = scale_and_translation_transform_batch(pred_joints3D_h36mlsp,
                                                                             target_joints3D_h36mlsp)
            mpjpe_sc_batch = np.linalg.norm(pred_joints3D_h36mlsp_sc - target_joints3D_h36mlsp, axis=-1)  # (bsize, 14) or (num views, 14)
            self.metric_sums['mpjpes_sc'] += np.sum(mpjpe_sc_batch)  # scalar
            self.per_frame_metrics['mpjpes_sc'].append(np.mean(mpjpe_sc_batch, axis=-1))  # (bs,) or (num views,)
            if return_transformed_points:
                transformed_points_return_dict['pred_joints3D_h36mlsp_sc'] = pred_joints3D_h36mlsp_sc
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['mpjpes_sc'] = np.mean(mpjpe_sc_batch, axis=-1)

        # Procrustes analysis
        if 'mpjpes_pa' in self.metrics_to_track:
            pred_joints3D_h36mlsp = pred_dict['joints3D']  # (bsize, 14, 3) or (num views, 14, 3)
            target_joints3D_h36mlsp = target_dict['joints3D']  # (bsize, 14, 3) or (num views, 14, 3)
            pred_joints3D_h36mlsp_pa = procrustes_analysis_batch(pred_joints3D_h36mlsp,
                                                                 target_joints3D_h36mlsp)
            mpjpe_pa_batch = np.linalg.norm(pred_joints3D_h36mlsp_pa - target_joints3D_h36mlsp, axis=-1)  # (bsize, 14) or (num views, 14)
            self.metric_sums['mpjpes_pa'] += np.sum(mpjpe_pa_batch)  # scalar
            self.per_frame_metrics['mpjpes_pa'].append(np.mean(mpjpe_pa_batch, axis=-1))  # (bs,) or (num views,)
            if return_transformed_points:
                transformed_points_return_dict['pred_joints3D_h36mlsp_pa'] = pred_joints3D_h36mlsp_pa
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['mpjpes_pa'] = np.mean(mpjpe_pa_batch, axis=-1)

        if 'pves_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pve_per_sample = np.linalg.norm(pred_dict['verts_samples'] - target_dict['verts'], axis=-1)  # (num samples, 6890)
            min_pve_sample = np.argmin(np.mean(pve_per_sample, axis=-1))
            pve_samples_min_batch = pve_per_sample[min_pve_sample]
            self.metric_sums['pves_samples_min'] += np.sum(pve_samples_min_batch)  # scalar
            self.per_frame_metrics['pves_samples_min'].append(np.mean(pve_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        # Scale and translation correction
        if 'pves_sc_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pred_vertices_samples = pred_dict['verts_samples']  # (num samples, 6890, 3)
            target_vertices = np.tile(target_dict['verts'], (pred_vertices_samples.shape[0], 1, 1))  # (num samples, 6890, 3)
            pred_vertices_samples_sc = scale_and_translation_transform_batch(pred_vertices_samples, target_vertices)
            pve_sc_per_sample = np.linalg.norm(pred_vertices_samples_sc - target_vertices, axis=-1)  # (num samples, 6890)
            min_pve_sc_sample = np.argmin(np.mean(pve_sc_per_sample, axis=-1))
            pve_sc_samples_min_batch = pve_sc_per_sample[min_pve_sc_sample]
            self.metric_sums['pves_sc_samples_min'] += np.sum(pve_sc_samples_min_batch)  # scalar
            self.per_frame_metrics['pves_sc_samples_min'].append(np.mean(pve_sc_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        # Procrustes analysis
        if 'pves_pa_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pred_vertices_samples = pred_dict['verts_samples']  # (num samples, 6890, 3)
            target_vertices = np.tile(target_dict['verts'], (pred_vertices_samples.shape[0], 1, 1))  # (num samples, 6890, 3)
            pred_vertices_samples_pa = procrustes_analysis_batch(pred_vertices_samples, target_vertices)
            pve_pa_per_sample = np.linalg.norm(pred_vertices_samples_pa - target_vertices, axis=-1)  # (num samples, 6890)
            min_pve_pa_sample = np.argmin(np.mean(pve_pa_per_sample, axis=-1))
            pve_pa_samples_min_batch = pve_pa_per_sample[min_pve_pa_sample]
            self.metric_sums['pves_pa_samples_min'] += np.sum(pve_pa_samples_min_batch)  # scalar
            self.per_frame_metrics['pves_pa_samples_min'].append(np.mean(pve_pa_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        # Reposed
        if 'pve-ts_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pvet_per_sample = np.linalg.norm(pred_dict['reposed_verts_samples'] - target_dict['reposed_verts'],
                                             axis=-1)  # (num samples, 6890)
            min_pvet_sample = np.argmin(np.mean(pvet_per_sample, axis=-1))
            pvet_samples_min_batch = pvet_per_sample[min_pvet_sample]
            self.metric_sums['pve-ts_samples_min'] += np.sum(pvet_samples_min_batch)  # scalar
            self.per_frame_metrics['pve-ts_samples_min'].append(np.mean(pvet_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        # Reposed + Scale and translation correction
        if 'pve-ts_sc_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pred_reposed_vertices_samples = pred_dict['reposed_verts_samples']  # (num samples, 6890, 3)
            target_reposed_vertices = np.tile(target_dict['reposed_verts'],
                                              (pred_reposed_vertices_samples.shape[0], 1, 1))  # (num samples, 6890, 3)
            pred_reposed_vertices_samples_sc = scale_and_translation_transform_batch(pred_reposed_vertices_samples,
                                                                                     target_reposed_vertices)
            pvet_sc_per_sample = np.linalg.norm(pred_reposed_vertices_samples_sc - target_reposed_vertices, axis=-1)  # (num samples, 6890)
            min_pvet_sc_sample = np.argmin(np.mean(pvet_sc_per_sample, axis=-1))
            pvet_sc_samples_min_batch = pvet_sc_per_sample[min_pvet_sc_sample]
            self.metric_sums['pve-ts_sc_samples_min'] += np.sum(pvet_sc_samples_min_batch)  # scalar
            self.per_frame_metrics['pve-ts_sc_samples_min'].append(np.mean(pvet_sc_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        if 'mpjpes_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            mpjpe_per_sample = np.linalg.norm(pred_dict['joints3D_samples'] - target_dict['joints3D'], axis=-1)  # (num samples, 14))
            min_mpjpe_sample = np.argmin(np.mean(mpjpe_per_sample, axis=-1))
            mpjpe_samples_min_batch = mpjpe_per_sample[min_mpjpe_sample]
            self.metric_sums['mpjpes_samples_min'] += np.sum(mpjpe_samples_min_batch)  # scalar
            self.per_frame_metrics['mpjpes_samples_min'].append(np.mean(mpjpe_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        # Scale and translation correction
        if 'mpjpes_sc_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pred_joints3D_h36mlsp_samples = pred_dict['joints3D_samples']  # (num samples, 14, 3)
            target_joints3D_h36mlsp = np.tile(target_dict['joints3D'],
                                              (pred_joints3D_h36mlsp_samples.shape[0], 1, 1))  # (num samples, 14, 3)
            pred_joints3D_h36mlsp_sc = scale_and_translation_transform_batch(pred_joints3D_h36mlsp_samples,
                                                                             target_joints3D_h36mlsp)
            mpjpe_sc_per_sample = np.linalg.norm(pred_joints3D_h36mlsp_sc - target_joints3D_h36mlsp, axis=-1)  # (num samples, 14)
            min_mpjpe_sc_sample = np.argmin(np.mean(mpjpe_sc_per_sample, axis=-1))
            mpjpe_sc_samples_min_batch = mpjpe_sc_per_sample[min_mpjpe_sc_sample]
            self.metric_sums['mpjpes_sc_samples_min'] += np.sum(mpjpe_sc_samples_min_batch)  # scalar
            self.per_frame_metrics['mpjpes_sc_samples_min'].append(np.mean(mpjpe_sc_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        # Procrustes analysis
        if 'mpjpes_pa_samples_min' in self.metrics_to_track:
            assert num_input_samples == 1, "Batch size must be 1 for min samples metrics!"
            pred_joints3D_h36mlsp_samples = pred_dict['joints3D_samples']  # (num samples, 14, 3)
            target_joints3D_h36mlsp = np.tile(target_dict['joints3D'],
                                              (pred_joints3D_h36mlsp_samples.shape[0], 1, 1))  # (num samples, 14, 3)
            pred_joints3D_h36mlsp_pa = procrustes_analysis_batch(pred_joints3D_h36mlsp_samples,
                                                                 target_joints3D_h36mlsp)
            mpjpe_pa_per_sample = np.linalg.norm(pred_joints3D_h36mlsp_pa - target_joints3D_h36mlsp, axis=-1)  # (num samples, 14)
            min_mpjpe_pa_sample = np.argmin(np.mean(mpjpe_pa_per_sample, axis=-1))
            mpjpe_pa_samples_min_batch = mpjpe_pa_per_sample[min_mpjpe_pa_sample]
            self.metric_sums['mpjpes_pa_samples_min'] += np.sum(mpjpe_pa_samples_min_batch)  # scalar
            self.per_frame_metrics['mpjpes_pa_samples_min'].append(np.mean(mpjpe_pa_samples_min_batch, axis=-1))  # (1,) i.e. scalar

        if 'pose_mses' in self.metrics_to_track:
            self.metric_sums['pose_mses'] += np.sum((pred_dict['pose_params_rot_matrices'] -
                                                     target_dict['pose_params_rot_matrices']) ** 2)

        if 'shape_mses' in self.metrics_to_track:
            self.metric_sums['shape_mses'] += np.sum((pred_dict['shape_params'] -
                                                      target_dict['shape_params']) ** 2)

        if 'joints2D_l2es' in self.metrics_to_track:
            pred_joints2D_coco = pred_dict['joints2D']  # (bsize, 17, 2) or (num views, 17, 2)
            target_joints2D_coco = target_dict['joints2D']  # (bsize, 17, 2) or (num views, 17, 2)
            joints2D_l2e_batch = np.linalg.norm(pred_joints2D_coco - target_joints2D_coco, axis=-1)  # (bsize, 17) or (num views, 17)
            self.metric_sums['joints2D_l2es'] += np.sum(joints2D_l2e_batch)  # scalar
            self.per_frame_metrics['joints2D_l2es'].append(np.mean(joints2D_l2e_batch, axis=-1))  # (bs,) or (num views,)
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['joints2D_l2es'] = np.mean(joints2D_l2e_batch, axis=-1)

        if 'joints2Dsamples_l2es' in self.metrics_to_track:
            pred_joints2D_coco_samples = pred_dict['joints2Dsamples']  # (bsize, num_samples, 17, 2)
            target_joints2D_coco = np.tile(target_dict['joints2D'][:, None, :, :], (1, pred_joints2D_coco_samples.shape[1], 1, 1))  # (bsize, num_samples, 17, 2)
            if 'joints2D_vis' in target_dict.keys():
                target_joints2d_vis_coco = np.tile(target_dict['joints2D_vis'][:, None, :], (1, pred_joints2D_coco_samples.shape[1], 1))  # (bsize, num_samples, 17)
                pred_joints2D_coco_samples = pred_joints2D_coco_samples[target_joints2d_vis_coco, :]  # (N, 2)
                target_joints2D_coco = target_joints2D_coco[target_joints2d_vis_coco, :]  # (N, 2)
            joints2Dsamples_l2e_batch = np.linalg.norm(pred_joints2D_coco_samples - target_joints2D_coco, axis=-1)  # (N,) or (bsize, num_samples, 17)
            if 'joints2D_vis' in target_dict.keys():
                assert joints2Dsamples_l2e_batch.shape[0] == target_joints2d_vis_coco.sum()
            joints2Dsamples_l2e_batch = joints2Dsamples_l2e_batch.reshape(-1)
            self.metric_sums['joints2Dsamples_l2es'] += np.sum(joints2Dsamples_l2e_batch)  # scalar
            self.metric_sums['num_vis_joints2Dsamples'] += joints2Dsamples_l2e_batch.shape[0]

        if 'silhouette_ious' in self.metrics_to_track:
            pred_silhouettes = pred_dict['silhouettes']  # (bsize, img_wh, img_wh) or (num views, img_wh, img_wh)
            target_silhouettes = target_dict['silhouettes']  # (bsize, img_wh, img_wh) or (num views, img_wh, img_wh)
            true_positive = np.logical_and(pred_silhouettes, target_silhouettes)
            false_positive = np.logical_and(pred_silhouettes, np.logical_not(target_silhouettes))
            true_negative = np.logical_and(np.logical_not(pred_silhouettes), np.logical_not(target_silhouettes))
            false_negative = np.logical_and(np.logical_not(pred_silhouettes), target_silhouettes)
            num_tp = np.sum(true_positive, axis=(1, 2))  # (bsize,) or (num views,)
            num_fp = np.sum(false_positive, axis=(1, 2))
            num_tn = np.sum(true_negative, axis=(1, 2))
            num_fn = np.sum(false_negative, axis=(1, 2))
            self.metric_sums['num_true_positives'] += np.sum(num_tp)  # scalar
            self.metric_sums['num_false_positives'] += np.sum(num_fp)
            self.metric_sums['num_true_negatives'] += np.sum(num_tn)
            self.metric_sums['num_false_negatives'] += np.sum(num_fn)
            iou_per_frame = num_tp/(num_tp + num_fp + num_fn)
            self.per_frame_metrics['silhouette_ious'].append(iou_per_frame)  # (bs,) or (num views,)
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['silhouette_ious'] = iou_per_frame

        if 'silhouettesamples_ious' in self.metrics_to_track:
            pred_silhouettes_samples = pred_dict['silhouettessamples']  # (bsize, num_samples, img_wh, img_wh)
            target_silhouettes = np.tile(target_dict['silhouettes'][:, None, :, :], (1, pred_silhouettes_samples.shape[1], 1, 1))  # (bsize, num_samples, img_wh, img_wh)
            true_positive = np.logical_and(pred_silhouettes_samples, target_silhouettes)
            false_positive = np.logical_and(pred_silhouettes_samples, np.logical_not(target_silhouettes))
            true_negative = np.logical_and(np.logical_not(pred_silhouettes_samples), np.logical_not(target_silhouettes))
            false_negative = np.logical_and(np.logical_not(pred_silhouettes_samples), target_silhouettes)
            num_tp = np.sum(true_positive, axis=(1, 2))  # (bsize,) or (num views,)
            num_fp = np.sum(false_positive, axis=(1, 2))
            num_tn = np.sum(true_negative, axis=(1, 2))
            num_fn = np.sum(false_negative, axis=(1, 2))
            self.metric_sums['num_samples_true_positives'] += np.sum(num_tp)  # scalar
            self.metric_sums['num_samples_false_positives'] += np.sum(num_fp)
            self.metric_sums['num_samples_true_negatives'] += np.sum(num_tn)
            self.metric_sums['num_samples_false_negatives'] += np.sum(num_fn)

        if 'measurements_mae' in self.metrics_to_track:
            error_dict = {}
            for measure in config.METAIL_MEASUREMENTS:
                error = pred_dict['measurements'][measure] - target_dict['measurements'][measure]
                self.metric_sums[measure] += np.abs(error)
                error_dict[measure] = error
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['measurements'] = error_dict

        if 'smpl_measurements_mae' in self.metrics_to_track:
            target_reposed_vertices = target_dict['reposed_verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            target_reposed_joints = target_dict['reposed_joints']  # (bsize, 90, 3) or (num views, 90, 3)
            pred_reposed_vertices = pred_dict['reposed_verts']  # (bsize, 6890, 3) or (num views, 6890, 3)
            pred_reposed_joints = pred_dict['reposed_joints']  # (bsize, 90, 3) or (num views, 90, 3)
            pred_reposed_vertices_sc = scale_and_translation_transform_batch(pred_reposed_vertices,
                                                                             target_reposed_vertices)
            pred_reposed_joints_sc = scale_and_translation_transform_batch(pred_reposed_joints,
                                                                           target_reposed_joints)

            target_joint_length_meas, target_vertex_length_meas, target_vertex_circum_meas = get_measurements_from_vertices(vertices=torch.from_numpy(target_reposed_vertices),
                                                                                                                            joints_all=torch.from_numpy(target_reposed_joints))
            target_measurements = torch.cat([target_joint_length_meas,
                                             target_vertex_length_meas,
                                             target_vertex_circum_meas],
                                            dim=-1)
            target_measurements = remove_symmetric_measurements_torch(target_meas=target_measurements,
                                                                      target_meas_names=config.ALL_MEAS_NAMES,
                                                                      combine_using='mean').cpu().detach().numpy()

            pred_joint_length_meas, pred_vertex_length_meas, pred_vertex_circum_meas = get_measurements_from_vertices(vertices=torch.from_numpy(pred_reposed_vertices_sc),
                                                                                                                      joints_all=torch.from_numpy(pred_reposed_joints_sc))
            pred_measurements = torch.cat([pred_joint_length_meas,
                                           pred_vertex_length_meas,
                                           pred_vertex_circum_meas],
                                          dim=-1)
            pred_measurements = remove_symmetric_measurements_torch(target_meas=pred_measurements,
                                                                    target_meas_names=config.ALL_MEAS_NAMES,
                                                                    combine_using='mean').cpu().detach().numpy()

            error_dict = {}
            for i, measure in enumerate(config.ALL_MEAS_NAMES_NO_SYMM):
                # error = pred_dict['smpl_measurements'][:, i] - target_dict['smpl_measurements'][:, i]  # (bsize, )
                error = target_measurements[:, i] - pred_measurements[:, i]
                self.metric_sums[measure] += np.sum(np.abs(error))  # scalar
                error_dict[measure] = error
            # self.metric_sums['smpl_meas_error_all'] += np.sum(np.abs(pred_dict['smpl_measurements'] - target_dict['smpl_measurements']))
            self.metric_sums['smpl_meas_error_all'] += np.sum(np.abs(target_measurements - pred_measurements))
            if return_per_frame_metrics:
                per_frame_metrics_return_dict['smpl_measurements'] = error_dict

        return transformed_points_return_dict, per_frame_metrics_return_dict

    def compute_final_metrics(self):
        final_metrics = {}
        for metric_type in self.metrics_to_track:
            if metric_type == 'silhouette_ious':
                iou = self.metric_sums['num_true_positives'] / \
                      (self.metric_sums['num_true_positives'] +
                       self.metric_sums['num_false_negatives'] +
                       self.metric_sums['num_false_positives'])
                final_metrics['silhouette_ious'] = iou
            elif metric_type == 'silhouettesamples_ious':
                iou = self.metric_sums['num_samples_true_positives'] / \
                      (self.metric_sums['num_samples_true_positives'] +
                       self.metric_sums['num_samples_false_negatives'] +
                       self.metric_sums['num_samples_false_positives'])
                final_metrics['silhouettesamples_ious'] = iou
            elif metric_type == 'joints2Dsamples_l2es':
                joints2Dsamples_l2e = self.metric_sums['joints2Dsamples_l2es'] / self.metric_sums['num_vis_joints2Dsamples']
                final_metrics[metric_type] = joints2Dsamples_l2e
            elif metric_type == 'measurements_mae':
                for measure in config.METAIL_MEASUREMENTS:
                    final_metrics[measure] = self.metric_sums[measure] / self.total_samples
            elif metric_type == 'smpl_measurements_mae':
                for measure in config.ALL_MEAS_NAMES_NO_SYMM:
                    final_metrics[measure] = self.metric_sums[measure] / self.total_samples
                final_metrics['smpl_meas_error_all'] = self.metric_sums['smpl_meas_error_all'] / (self.total_samples * 23)
            else:
                if 'pve' in metric_type:
                    num_per_sample = 6890
                elif 'mpjpe' in metric_type:
                    num_per_sample = 14
                elif 'joints2D_' in metric_type:
                    num_per_sample = 17
                elif 'shape_mse' in metric_type:
                    num_per_sample = 10
                elif 'pose_mse' in metric_type:
                    num_per_sample = 24 * 3 * 3

                print(metric_type, num_per_sample, self.total_samples)
                final_metrics[metric_type] = self.metric_sums[metric_type] / (self.total_samples * num_per_sample)
        for metric in final_metrics.keys():
            if final_metrics[metric] > 0.3:
                mult = 1
            else:
                mult = 1000
            print(metric, '{:.2f}'.format(final_metrics[metric]*mult))  # Converting from metres to millimetres
        if self.save_per_frame_metrics:
            for metric_type in self.metrics_to_track:
                if 'samples' not in metric_type and 'measurements' not in metric_type:
                    per_frame = np.concatenate(self.per_frame_metrics[metric_type], axis=0)
                    # TODO printing for debugging - remove later
                    print(metric_type, per_frame.shape)
                    np.save(os.path.join(self.save_path, metric_type+'_per_frame.npy'), per_frame)