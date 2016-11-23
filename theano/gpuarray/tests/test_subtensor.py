from __future__ import absolute_import, print_function, division
import numpy
import unittest

import theano
from theano import tensor
from theano.compile import DeepCopyOp
from theano.tensor.tests import test_subtensor

from ..basic_ops import HostFromGpu, GpuFromHost
from ..elemwise import GpuDimShuffle
from ..subtensor import (GpuIncSubtensor, GpuSubtensor,
                         GpuAdvancedSubtensor1,
                         GpuAdvancedSubtensor,
                         GpuAdvancedIncSubtensor1,
                         GpuDiagonal)
from ..type import gpuarray_shared_constructor

from .config import mode_with_gpu, floatX


class G_subtensor(test_subtensor.T_subtensor):
    def shortDescription(self):
        return None

    def __init__(self, name):
        test_subtensor.T_subtensor.__init__(
            self, name,
            shared=gpuarray_shared_constructor,
            sub=GpuSubtensor,
            inc_sub=GpuIncSubtensor,
            adv_sub1=GpuAdvancedSubtensor1,
            adv_incsub1=GpuAdvancedIncSubtensor1,
            dimshuffle=GpuDimShuffle,
            mode=mode_with_gpu,
            # avoid errors with limited devices
            dtype='float32',
            ignore_topo=(HostFromGpu, GpuFromHost,
                         DeepCopyOp))
        # GPU opt can't run in fast_compile only.
        self.fast_compile = False
        assert self.sub == GpuSubtensor


def test_advinc_subtensor1():
    # Test the second case in the opt local_gpu_advanced_incsubtensor1
    for shp in [(3, 3), (3, 3, 3)]:
        shared = gpuarray_shared_constructor
        xval = numpy.arange(numpy.prod(shp), dtype='float32').reshape(shp) + 1
        yval = numpy.empty((2,) + shp[1:], dtype='float32')
        yval[:] = 10
        x = shared(xval, name='x')
        y = tensor.tensor(dtype='float32',
                          broadcastable=(False,) * len(shp),
                          name='y')
        expr = tensor.advanced_inc_subtensor1(x, y, [0, 2])
        f = theano.function([y], expr, mode=mode_with_gpu)
        assert sum([isinstance(node.op, GpuAdvancedIncSubtensor1)
                    for node in f.maker.fgraph.toposort()]) == 1
        rval = f(yval)
        rep = xval.copy()
        rep[[0, 2]] += yval
        assert numpy.allclose(rval, rep)


def test_incsub_f16():
    shp = (3, 3)
    shared = gpuarray_shared_constructor
    xval = numpy.arange(numpy.prod(shp), dtype='float16').reshape(shp) + 1
    yval = numpy.empty((2,) + shp[1:], dtype='float16')
    yval[:] = 2
    x = shared(xval, name='x')
    y = tensor.tensor(dtype='float16',
                      broadcastable=(False,) * len(shp),
                      name='y')
    expr = tensor.advanced_inc_subtensor1(x, y, [0, 2])
    f = theano.function([y], expr, mode=mode_with_gpu)
    assert sum([isinstance(node.op, GpuAdvancedIncSubtensor1)
                for node in f.maker.fgraph.toposort()]) == 1
    rval = f(yval)
    rep = xval.copy()
    rep[[0, 2]] += yval
    assert numpy.allclose(rval, rep)

    expr = tensor.inc_subtensor(x[1:], y)
    f = theano.function([y], expr, mode=mode_with_gpu)
    assert sum([isinstance(node.op, GpuIncSubtensor)
                for node in f.maker.fgraph.toposort()]) == 1
    rval = f(yval)
    rep = xval.copy()
    rep[1:] += yval
    assert numpy.allclose(rval, rep)


class G_advancedsubtensor(test_subtensor.TestAdvancedSubtensor):
    def shortDescription(self):
        return None

    def __init__(self, name):
        test_subtensor.TestAdvancedSubtensor.__init__(
            self, name,
            shared=gpuarray_shared_constructor,
            sub=GpuAdvancedSubtensor,
            mode=mode_with_gpu,
            # avoid errors with limited devices
            dtype='float32',
            ignore_topo=(HostFromGpu, GpuFromHost,
                         DeepCopyOp))
        # GPU opt can't run in fast_compile only.
        self.fast_compile = False
        assert self.sub == GpuAdvancedSubtensor


def test_adv_subtensor():
    # Test the advancedsubtensor on gpu.
    shp = (2, 3, 4)
    shared = gpuarray_shared_constructor
    xval = numpy.arange(numpy.prod(shp), dtype=theano.config.floatX).reshape(shp)
    idx1, idx2 = tensor.ivectors('idx1', 'idx2')
    idxs = [idx1, None, slice(0, 2, 1), idx2, None]
    x = shared(xval, name='x')
    expr = x[idxs]
    f = theano.function([idx1, idx2], expr, mode=mode_with_gpu)
    assert sum([isinstance(node.op, GpuAdvancedSubtensor)
               for node in f.maker.fgraph.toposort()]) == 1
    idx1_val = [0, 1]
    idx2_val = [0, 1]
    rval = f(idx1_val, idx2_val)
    rep = xval[idx1_val, None, slice(0, 2, 1), idx2_val, None]
    assert numpy.allclose(rval, rep)


class test_gpudiagonal(unittest.TestCase):
    def test_matrix(self):
        x = tensor.fmatrix()
        np_x = numpy.arange(77).reshape(7, 11).astype('float32')
        fn = theano.function([x], GpuDiagonal()(x), mode=mode_with_gpu)
        assert numpy.allclose(fn(np_x), np_x.diagonal())
        fn = theano.function([x], GpuDiagonal(2)(x), mode=mode_with_gpu)
        assert numpy.allclose(fn(np_x), np_x.diagonal(2))
        fn = theano.function([x], GpuDiagonal(-3)(x), mode=mode_with_gpu)
        assert numpy.allclose(fn(np_x), np_x.diagonal(-3))

    def test_tensor(self):
        x = tensor.ftensor4()
        np_x = numpy.arange(30107).reshape(7, 11, 17, 23).astype(floatX)
        for offset, axis1, axis2 in [
                (1, 0, 1), (-1, 0, 1), (0, 1, 0), (-2, 1, 0),
                (-3, 1, 0), (-2, 2, 0), (3, 3, 0), (-1, 3, 2),
                (2, 2, 3), (-1, 2, 1), (1, 3, 1), (-1, 1, 3)]:
            assert numpy.allclose(
                GpuDiagonal(offset, axis1, axis2)(x).eval({x: np_x}),
                np_x.diagonal(offset, axis1, axis2))
