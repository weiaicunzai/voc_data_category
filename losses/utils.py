# Copyright (c) OpenMMLab. All rights reserved.
import functools

# import mmcv
import numpy as np
import torch
import torch.nn.functional as F


#def get_class_weight(class_weight):
#    """Get class weight for loss function.
#    Args:
#        class_weight (list[float] | str | None): If class_weight is a str,
#            take it as a file name and read from it.
#    """
#    if isinstance(class_weight, str):
#        # take it as a file path
#        if class_weight.endswith('.npy'):
#            class_weight = np.load(class_weight)
#        else:
#            # pkl, json or yaml
#            class_weight = mmcv.load(class_weight)
#
#    return class_weight


def reduce_loss(loss, reduction):
    """Reduce loss as specified.
    Args:
        loss (Tensor): Elementwise loss tensor.
        reduction (str): Options are "none", "mean" and "sum".
    Return:
        Tensor: Reduced loss tensor.
    """
    reduction_enum = F._Reduction.get_enum(reduction)
    # none: 0, elementwise_mean:1, sum: 2
    if reduction_enum == 0:
        return loss
    elif reduction_enum == 1:
        return loss.mean()
    elif reduction_enum == 2:
        return loss.sum()


def weight_reduce_loss(loss, weight=None, reduction='mean', avg_factor=None):
    """Apply element-wise weight and reduce loss.
    Args:
        loss (Tensor): Element-wise loss.
        weight (Tensor): Element-wise weights.
        reduction (str): Same as built-in losses of PyTorch.
        avg_factor (float): Average factor when computing the mean of losses.
    Returns:
        Tensor: Processed loss values.
    """
    # if weight is specified, apply element-wise weight
    if weight is not None:
        assert weight.dim() == loss.dim()
        if weight.dim() > 1:
            assert weight.size(1) == 1 or weight.size(1) == loss.size(1)
        loss = loss * weight

    # if avg_factor is not specified, just reduce the loss
    if avg_factor is None:
        loss = reduce_loss(loss, reduction)
    else:
        # if reduction is mean, then average the loss by avg_factor
        if reduction == 'mean':
            # Avoid causing ZeroDivisionError when avg_factor is 0.0,
            # i.e., all labels of an image belong to ignore index.
            eps = torch.finfo(torch.float32).eps
            loss = loss.sum() / (avg_factor + eps)
        # if reduction is 'none', then do nothing, otherwise raise an error
        elif reduction != 'none':
            raise ValueError('avg_factor can not be used with reduction="sum"')
    return loss


def weighted_loss(loss_func):
    """Create a weighted version of a given loss function.
    To use this decorator, the loss function must have the signature like
    `loss_func(pred, target, **kwargs)`. The function only needs to compute
    element-wise loss without any reduction. This decorator will add weight
    and reduction arguments to the function. The decorated function will have
    the signature like `loss_func(pred, target, weight=None, reduction='mean',
    avg_factor=None, **kwargs)`.
    :Example:
    >>> import torch
    >>> @weighted_loss
    >>> def l1_loss(pred, target):
    >>>     return (pred - target).abs()
    >>> pred = torch.Tensor([0, 2, 3])
    >>> target = torch.Tensor([1, 1, 1])
    >>> weight = torch.Tensor([1, 0, 1])
    >>> l1_loss(pred, target)
    tensor(1.3333)
    >>> l1_loss(pred, target, weight)
    tensor(1.)
    >>> l1_loss(pred, target, reduction='none')
    tensor([1., 1., 2.])
    >>> l1_loss(pred, target, weight, avg_factor=2)
    tensor(1.5000)
    """

    @functools.wraps(loss_func)
    def wrapper(pred,
                target,
                weight=None,
                reduction='mean',
                avg_factor=None,
                **kwargs):
        # get element-wise loss
        loss = loss_func(pred, target, **kwargs)
        loss = weight_reduce_loss(loss, weight, reduction, avg_factor)
        return loss

    return wrapper


class WeightedLossWarpper:
    def __init__(self, loss_fn, sampler=None):
        self.loss_fn = loss_fn
        self.sampler = sampler

    def __call__(self, preds, masks):
        if self.sampler is not None:
            seg_weight = self.sampler.sample(preds, masks.unsqueeze(1))

        loss = self.loss_fn(preds, masks)

        if self.sampler is not None:
            loss = loss * seg_weight

        return loss


def connected_components(image: torch.Tensor, num_iterations: int = 100) -> torch.Tensor:
    r"""Computes the Connected-component labelling (CCL) algorithm.
    .. image:: https://github.com/kornia/data/raw/main/cells_segmented.png
    The implementation is an adaptation of the following repository:
    https://gist.github.com/efirdc/5d8bd66859e574c683a504a4690ae8bc
    .. warning::
        This is an experimental API subject to changes and optimization improvements.
    .. note::
       See a working example `here <https://kornia-tutorials.readthedocs.io/en/latest/
       connected_components.html>`__.
    Args:
        image: the binarized input image with shape :math:`(*, 1, H, W)`.
          The image must be in floating point with range [0, 1].
        num_iterations: the number of iterations to make the algorithm to converge.
    Return:
        The labels image with the same shape of the input image.
    Example:
        >>> img = torch.rand(2, 1, 4, 5)
        >>> img_labels = connected_components(img, num_iterations=100)
    """
    if not isinstance(image, torch.Tensor):
        raise TypeError(f"Input imagetype is not a torch.Tensor. Got: {type(image)}")

    if not isinstance(num_iterations, int) or num_iterations < 1:
        raise TypeError("Input num_iterations must be a positive integer.")

    if len(image.shape) < 3 or image.shape[-3] != 1:
        raise ValueError(f"Input image shape must be (*,1,H,W). Got: {image.shape}")

    H, W = image.shape[-2:]
    image_view = image.view(-1, 1, H, W)

    # precompute a mask with the valid values
    mask = image_view == 1

    # allocate the output tensors for labels
    B, _, _, _ = image_view.shape
    out = torch.arange(B * H * W, device=image.device, dtype=image.dtype).view((-1, 1, H, W))
    out[~mask] = 0

    for _ in range(num_iterations):
        out[mask] = F.max_pool2d(out, kernel_size=3, stride=1, padding=1)[mask]

    return out.view_as(image)
