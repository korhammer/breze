# -*- coding: utf-8 -*-

"""Module containing models for Gaussian processes."""


import numpy as np
import theano.tensor as T

from theano.sandbox.linalg.ops import MatrixInverse, Det, psd, Cholesky
minv = MatrixInverse()
det = Det()
cholesky = Cholesky()

from ..util import ParameterSet, Model, lookup
from ..component import misc, kernel as kernel_


class GaussianProcess(Model):

    minimal_noise = 1e-2
    minimal_length_scale = 1e-8

    def __init__(self, n_inpt, kernel='linear'):
        self.n_inpt = n_inpt
        self.kernel = kernel
        self.f_predict = None

        super(GaussianProcess, self).__init__()

    def init_pars(self):
        parspec = self.get_parameter_spec(self.n_inpt)
        self.parameters = ParameterSet(**parspec)

    def init_exprs(self):
        self.exprs = self.make_exprs(
            T.matrix('inpt'), T.matrix('test_inpt'),
            T.matrix('target'),
            self.parameters.length_scales, self.parameters.noise,
            self.parameters.amplitude,
            self.kernel)

    @staticmethod
    def get_parameter_spec(n_inpt):
        return dict(length_scales=n_inpt, noise=1, amplitude=1)

    @staticmethod
    def make_exprs(inpt, test_inpt, target,
                   length_scales, noise, amplitude, kernel):

        # To stay compatible to the prediction api, target will
        # be a matrix to the outside. But in the following, it's easier
        # if it is a vector in the inside. We keep a reference to the
        # matrix anyway, to return it.
        target_ = target
        target = target[:, 0]
        noise = T.exp(noise) + GaussianProcess.minimal_noise
        length_scales = T.exp(length_scales) + GaussianProcess.minimal_length_scale
        amplitude = T.exp(amplitude) + 1e-4

        kernel_func = lookup(kernel, kernel_)

        # For training.
        K = kernel_func(inpt, inpt, length_scales, amplitude)

        K += T.identity_like(K) * noise

        # Justin: This is an informed choice. I played around a little
        # with various methods (e.g. using cholesky first) and came to
        # the conclusion that this way of doing it was way faster than
        # anything else in my case.
        psd(K)
        inv_K = minv(K)

        n_samples = K.shape[0]
        nll = (
            0.5 * T.dot(T.dot(target.T, inv_K), target)
            + 0.5 * T.log(det(K) + 1e-8)
            + 0.5 * n_samples * T.log(2 * np.pi))

        # For prediction.
        inference_kernelrows = kernel_func(inpt, test_inpt, length_scales,
                                           amplitude)

        kTK = T.dot(inference_kernelrows.T, inv_K)
        output_mean = T.dot(kTK, target).dimshuffle(0, 'x')

        kTKk = T.dot(kTK, inference_kernelrows)

        chol_inv_K = cholesky(inv_K)

        diag_kTKk = (T.dot(chol_inv_K.T, inference_kernelrows)**2).sum(axis=0)
        test_K = kernel_func(test_inpt, test_inpt, length_scales, amplitude,
                             diag=True)
        output_var = ((test_K - diag_kTKk)).dimshuffle(0, 'x')

        return {
            'inpt': inpt,
            'test_inpt': test_inpt,
            'target': target_,
            'gram_matrix': K,
            'inv_gram_matrix': inv_K,
            'chol_inv_gram_matrix': chol_inv_K,
            'nll': nll,
            'loss': nll,
            'output': output_mean,
            'output_var': output_var,
            'inference_kernelrows': inference_kernelrows,
            'test_K': test_K,
            'kTKk': kTKk,
        }
