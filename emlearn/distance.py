
import os.path
import os

import numpy

from . import common, cgen

"""

References
https://github.com/scikit-learn/scikit-learn/blob/15a949460dbf19e5e196b8ef48f9712b72a3b3c3/sklearn/covariance/_empirical_covariance.py#L297

https://github.com/scikit-learn/scikit-learn/blob/15a949460dbf19e5e196b8ef48f9712b72a3b3c3/sklearn/covariance/_elliptic_envelope.py#L149

"""

from sklearn.mixture._gaussian_mixture import _compute_log_det_cholesky
from sklearn.utils.extmath import row_norms
np = numpy


def squared_mahalanobis_distance(x1, x2, precision):
    """    
    @precision is the inverted covariance matrix

    computes (x1 - x2).T * VI * (x1 - x2)
    where VI is the precision matrix, the inverse of the covariance matrix

    Loosely based on the scikit-learn implementation,
    https://github.com/scikit-learn/scikit-learn/blob/main/sklearn/neighbors/_dist_metrics.pyx
    """

    distance = 0.0
    size = x1.shape[0]
    temp = numpy.zeros(shape=size) 

    assert x1.shape == x2.shape
    assert precision.shape[0] == precision.shape[1]
    assert size == precision.shape[0]

    for i in range(size):
        accumulate = 0
        for j in range(size):
            accumulate += precision[i, j] * (x1[j] - x2[j])
        distance += accumulate * (x1[i] - x2[i])

    return distance


def generate_code(means, precision, offset, name='my_elliptic', modifiers='static const'):

    n_features = means.shape[0]
    decision_boundary = offset # FIXME, check
   
    classifier_name = f'{name}_classifier'
    means_name = f'{name}_means'
    precisions_name = f'{name}_precisions'
    predict_function_name = f'{name}_predict'

    includes = '''
    // This code is generated by emlearn

    #include <eml_distance.h>
    '''

    pre = '\n\n'.join([
        includes,
        cgen.array_declare(means_name, n_features, modifiers=modifiers, values=means),
        cgen.array_declare(precisions_name, n_features*n_features,
            modifiers=modifiers,
            values=precision.flatten(order='C'),
        ),
    ])

    main = f'''
    #include <stdio.h>

    // Data definitions
    {modifiers} EmlEllipticEnvelope {classifier_name} = {{
        {n_features},
        {decision_boundary},
        {means_name},
        {precisions_name}
    }};

    // Prediction function
    float {predict_function_name}(const float *features, int n_features) {{
        float dist = 0.0;
        const int class = eml_elliptic_envelope_predict(&{classifier_name},
                                features, n_features, &dist);
        return dist; 
    }}
    '''

    code = pre + main

    return code


class Wrapper:
    def __init__(self, estimator, classifier='inline', dtype='float'):
        self.dtype = dtype

        precision = estimator.get_precision()
        self._means = estimator.location_.copy()
        self._precision = precision
        self._offset = estimator.offset_

        if classifier == 'inline':
            name = 'my_inline_elliptic'
            func = '{}_predict(values, length)'.format(name)
            code = self.save(name=name)
            self.classifier_ = common.CompiledClassifier(code, name=name, call=func, out_dtype='float')
        else:
            raise ValueError("Unsupported classifier method '{}'".format(classifier))

    def mahalanobis(self, X):
        def dist(x):
            return squared_mahalanobis_distance(x, self._means, precision=self._precision)
        p = numpy.array([ dist(x) for x in X ])

        predictions = self.classifier_.predict(X)
        return predictions

    def predict(self, X):
        def predict_one(d):
            dist = -d
            dd = dist - self._offset
            is_inlier = 1 if dd > 0 else -1
            return is_inlier

        distances = self.mahalanobis(X)
        return numpy.array([predict_one(d) for d in distances])


    def save(self, name=None, file=None):
        if name is None:
            if file is None:
                raise ValueError('Either name or file must be provided')
            else:
                name = os.path.splitext(os.path.basename(file))[0]

        code = generate_code(self._means, self._precision, self._offset, name=name)
        if file:
            with open(file, 'w') as f:
                f.write(code)

        return code

