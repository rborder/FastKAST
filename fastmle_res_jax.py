from sklearn.kernel_approximation import RBFSampler
import numpy as np
import traceback
from scipy.optimize import minimize
import sys
import gc
from scipy.linalg import svd
import time
from numpy.linalg import inv
import scipy
from scipy.linalg import pinvh
import fastlmmclib.quadform as qf
from chi2comb import chi2comb_cdf, ChiSquared
from sklearn.linear_model import LogisticRegression
import scipy
from numpy.core.umath_tests import inner1d
from sklearn.preprocessing import PolynomialFeatures

# def jax_svd(X):
#     return svd(X, full_matrices = False, compute_uv=False).block_until_ready()


def scipy_svd(X):
    return scipy.linalg.svd(X, full_matrices=False, compute_uv=False)

def numpy_svd(X,compute_uv=False):
    return np.linalg.svd(X,full_matrices=False, compute_uv=compute_uv)

def lik2(param, *args):
    if len(args) == 1:
        nargs = args
        (n, Sii, UTy, LLadd1) = nargs[0]
    else:
        (n, Sii, UTy, LLadd1) = args
    logdelta = param[0]
    gamma = param[1]
    # gamma = 0
    UTy = UTy.flatten()
    nulity = max(0, n - len(Sii))
    L1 = (sum(np.log(Sii * np.exp(gamma) + np.exp(logdelta))) +
          nulity * logdelta) / 2  # The first part of the log likelihood
    sUTy = np.square(UTy)
    if LLadd1 is None:
        print('operation on L2')
        L2 = (n / 2.0) * np.log(
            (sum(sUTy / (Sii * np.exp(gamma) + np.exp(logdelta)))) / n)
    else:
        L2 = (n / 2.0) * np.log(
            (sum(sUTy / (Sii * np.exp(gamma) + np.exp(logdelta))) +
             (LLadd1 / (np.exp(logdelta)))) / n)
    return (L1 + L2)


def score_test(S):
    # N = Z.shape[0]
    k = len(S)
    dofs = np.ones(k)
    ncents = np.zeros(k)
    chi2s = [ChiSquared(S[i], ncents[i], dofs[i]) for i in range(k)]
    p, error, info = chi2comb_cdf(0, chi2s, 0, lim=10000000, atol=1e-14)
    # p = qf.qf(0, Phi, acc = 1e-7)[0]
    return (1 - p, error)


def score_test2(sq_sigma_e0, Q, S, decompose=True, center=False):
    k = len(S)
    Phi = np.zeros(k)
    Phi[0:len(S)] = S
    Qe = Q / (sq_sigma_e0)
    dofs = np.ones(k)
    ncents = np.zeros(k)
    chi2s = [ChiSquared(Phi[i], ncents[i], dofs[i]) for i in range(k)]
    t0 = time.time()
    p, error, info = chi2comb_cdf(Qe, chi2s, 0, lim=int(1e6), atol=1e-50)
    # p = qf.qf(0, Phi, acc = 1e-7)[0]
    t1 = time.time()
    return (1 - p, error)

def score_test_qf(sq_sigma_e0, Q, S, decompose=True, center=False):
    Qe = float(Q / (sq_sigma_e0))
    stats=qf.qf(Qe, S,sigma=1,lim=int(1e6),acc = 1e-50)
    p = stats[0]
    return (p)


def lik(logdelta, *args):
    if len(args) == 1:
        nargs = args
        (n, Sii, UTy, LLadd1) = nargs[0]
    else:
        (n, Sii, UTy, LLadd1) = args
    UTy = UTy.flatten()
    nulity = max(0, n - len(Sii))
    L1 = (sum(np.log(Sii + np.exp(logdelta))) +
          nulity * logdelta) / 2  # The first part of the log likelihood
    sUTy = np.square(UTy)
    if LLadd1 is None:
        L2 = (n / 2.0) * np.log((sum(sUTy / (Sii + np.exp(logdelta)))))
    else:
        L2 = (n / 2.0) * np.log((sum(sUTy / (Sii + np.exp(logdelta))) +
                                 (LLadd1 / (np.exp(logdelta)))))
    return (L1 + L2)


def standerr(U, y, Sii, UTy, g, e):
    L11 = np.sum(np.square(UTy.flatten()) * np.square(Sii) / (g * Sii + e)**3)
    L22 = np.sum(np.square(y - U @ UTy).flatten() / (e)**3) + np.sum(
        np.square(UTy).flatten() / ((e + Sii * g)**3))
    L12 = np.sum((np.square(UTy.flatten()) * Sii) / (g * Sii + e)**3)
    L = 0.5 * np.array([[L11, L12], [L12, L22]])
    cov = np.linalg.inv(L)
    gerr = np.sqrt(cov[0][0])
    eerr = np.sqrt(cov[1][1])
    return [gerr, eerr]


def dlik(logdelta, *args):
    n, Sii, UTy, LLadd1 = args
    UTy = UTy.flatten()
    delta = np.exp(logdelta)
    sUTy = np.square(UTy)
    if LLadd1 == None:
        LLadd1 = 0
    L1 = 0.5 * n * (np.sum(sUTy / np.square(Sii + delta)) +
                    LLadd1 / np.square(delta))
    L11 = np.sum(sUTy / (Sii + delta)) + LLadd1 / delta
    L2 = 0.5 * (np.sum(1 / (Sii + delta)) + (n - len(Sii)) * (1 / delta))
    der = np.zeros_like(delta)
    der[0] = -L1 / L11 + L2
    return der


def VarComponentEst(S, U, y, theta=False, dtype='quant',center=True):
    # delta is the initial guess of delta value
    n = y.shape[0]
    UTy = U.T @ y  # O(ND)
    if n > len(S):
        LLadd1 = np.sum(np.square(y - U @ UTy))
    else:
        LLadd1 = None
    # optimizer = brent(lik, args=(n, S, UTy, LLadd1), brack = (-10, 10))
    t0 = time.time()
    optimizer = (minimize(lik, [0], args=(n, S, UTy, LLadd1), method = 'Nelder-Mead', options={'maxiter':400}))
    # optimizer = (minimize(lik, [0],
    #                       args=(n, S, UTy, LLadd1),
    #                       method='L-BFGS-B',
    #                       jac=dlik,
    #                       options={
    #                           'maxcor': 15,
    #                           'ftol': 1e-10,
    #                           'gtol': 1e-9,
    #                           'maxfun': 30000,
    #                           'maxiter': 30000,
    #                           'maxls': 30
    #                       }))
    logdelta = optimizer.x[0]
    t1 = time.time()
    # print(f'optimization takes {t1-t0}')
    # logdelta = optimizer
    # fun = -1*lik(logdelta, n, S, UTy, LLadd1)
    fun = -1 * optimizer.fun

    delta = np.exp(logdelta)
    h = 1 / (delta + 1)  # heritability
    if LLadd1 == None:
        sq_sigma_g = (sum(np.square(UTy.flatten()) / (S + delta))) / n
    else:
        sq_sigma_g = (sum(np.square(UTy.flatten()) /
                          (S + delta)) + LLadd1 / delta) / n

    sq_sigma_e = delta * sq_sigma_g
    time0 = time.time()
    gerr, eerr = standerr(U, y, S, UTy, sq_sigma_g, sq_sigma_e)
    time1 = time.time()
    # print('error bound time is {}'.format(time1-time0))

    L1 = -lik(logdelta, n, S, UTy, LLadd1) - 0.5 * n * np.log(np.pi) - 0.5 * n
    yTy = (y.T @ y)[0]
    if dtype == 'quant':
        sq_sigma_e0 = yTy / n
    else:
        mu0 = np.sum(y) / n
        sq_sigma_e0 = mu0 * (1 - mu0)


#    sq_sigma_e0 = sq_sigma_e
    L0 = -0.5 * (n * np.log(np.pi) + n * np.log(sq_sigma_e0) +
                 yTy / sq_sigma_e0)
    return [
        h, sq_sigma_g, sq_sigma_e, gerr, eerr
    ]


def projection(Z, X, P1):
    # Perform (I-X(X^TX)^-1 X^T)Z
    Z = np.array(Z, order='F')
    X = np.array(X, order='F')
    P1 = np.array(P1, order='F')
    t1 = scipy.linalg.blas.sgemm(1., X, Z, trans_a=True)
    t2 = scipy.linalg.blas.sgemm(1., X, P1)
    t3 = scipy.linalg.blas.sgemm(1., t2, t1)
    Z = Z - t3
    return Z


def projection_2(Z, X, P1):
    Z = np.array(Z, order='F')
    X = np.array(X, order='F')
    P1 = np.array(P1, order='F')
    t1 = scipy.linalg.blas.sgemm(1., X, Z, trans_a=True)
    t3 = scipy.linalg.blas.sgemm(1., P1, t1)
    Z = Z - t3
    return Z


def inverse_2(X):
    inverse = inv(X.T @ X)
    result = scipy.linalg.blas.sgemm(1., X.T, inverse.T, trans_a=True)
    return result


def inverse(X):
    return pinvh(X.T @ X)  #change from pinv to inv sep 6
    # return pinvh(X.T@X)


def getfullComponent(X, Z, y, dtype='quant', center=False, method='Scipy'):
    # X is the covariates that need to be regressed out, res is the residule after regressing out the linear effect
    # delta is the initial guess of delta value
    f1 = time.time()
    t0 = time.time()
    n = Z.shape[0]
    print(f'Z: {Z}')
    if X.size > 1:
        X = np.concatenate((np.ones((n, 1)), X), axis=1)
    else:
        X = np.ones(n, 1)
    y = y.reshape(-1, 1)
    k = X.shape[1]
    yperm = np.random.permutation(y)
    P1 = inverse(X)
    start = time.time()
    t1 = time.time()
    print(f'inverse P1 takes {t1-t0}')
    if center:
        print(f'SVD for PKP')
        t1 = time.time()
        Z = projection(Z, X, P1)
        t0 = time.time()
        print(f'Z operation takes {t1-t0}')
    
        S = numpy_svd(Z)
        # S = scipy.linalg.svd(Z, full_matrices=False, compute_uv=False)
        t1 = time.time()
        print(f'svd takes {t1-t0}')
        t0 = time.time()
        #        Q = np.sum(np.square(y.T@Z))
        Q = np.sum(np.square(y.T @ Z - y.T @ X @ P1 @ X.T @ Z))
        Q_perm = np.sum(np.square(yperm.T @ Z - yperm.T @ X @ P1 @ X.T @ Z))
        t1 = time.time()
    else:
        SVD = svd(Z.T @ Z)
        Q = np.sum(np.square(y.T @ Z))
    t0 = time.time()
    #     S = np.square(SVD[1])
    ts0 = time.time()
    S = np.square(S)
    S[S <= 1e-6] = 0
    S = S[np.nonzero(S)]
    S = S[~np.isnan(S)]
    print(f'S: {S}')
    print(f'Q: {Q}')
    ts1 = time.time()
    # k = int(np.sum(inner1d(P1,X)))
    t1 = time.time()
    if center:
        # sq_sigma_e0 = (res.T@res)[0]/(n-k)
        sq_sigma_e0 = (y.T @ y - y.T @ X @ P1 @ (X.T @ y))[0] / (n - k)
        sq_sigma_e0_perm = (yperm.T @ yperm -
                            yperm.T @ X @ P1 @ (X.T @ yperm))[0] / (n - k)
    else:
        sq_sigma_e0 = y.T @ y / n
    t0 = time.time()
    #   def score_test(sq_sigma_e0, Z, yres, S, decompose=True,center=False):
    if center:
        p_value1 = score_test2(sq_sigma_e0, Q, S, center=center)
        p_value1_perm = score_test2(sq_sigma_e0_perm, Q_perm, S, center=center)
    else:
        p_value1 = score_test2(sq_sigma_e0, Q, S, center=center)
    t1 = time.time()
    print(f'p value is {p_value1}, p_value1_perm is {p_value1_perm}')
    # print('e is {}'.format(sq_sigma_e0))
    return [p_value1, p_value1_perm]


def getfullComponentPerm(X,
                         Z,
                         y,
                         theta=False,
                         dtype='quant',
                         center=False,
                         method='Numpy',
                         Perm=10,
                         Test='nonlinear',
                         VarCompEst=False):
    # X is the covariates that need to be regressed out, res is the residule after regressing out the linear effect
    # delta is the initial guess of delta value
    t0 = time.time()
    n = Z.shape[0]
    M = Z.shape[1]

    if X is None:
        X = np.ones((n, 1))
    else:
        X = np.concatenate((np.ones((n, 1)), X), axis=1)
    y = y.reshape(-1, 1)
    k = X.shape[1]
    # yperm = np.random.permutation(y)
    P1 = inverse(X)
    start = time.time()
    t1 = time.time()
    # print(f'inverse P1 takes {t1-t0}')
    # S = svd(Z.T@Z-(Z.T@P1)@(X.T@Z),compute_uv=False)
    t0 = time.time()
    # Z = left_projection(Z,X)
    # Z = projection_QR(Z,X,P1)
    Z = projection(Z, X, P1)
    # Z = Z - X@P1@(X.T@Z)
    t1 = time.time()
    # print(f'Z operation takes {t1-t0}')
    if VarCompEst:
        U,S,_ = numpy_svd(Z,compute_uv=True)
    else:
        S = numpy_svd(Z)
    # S = scipy.linalg.svd(Z, full_matrices=False, compute_uv=False)

    Q = np.sum(np.square(y.T @ Z - y.T @ X @ P1 @ X.T @ Z))

    t1 = time.time()
    # print(f'svd takes {t1-t0}')
    t0 = time.time()

    # Q_perm = np.sum(np.square(yperm.T@Z - yperm.T@X@P1@X.T@Z))
    t1 = time.time()
    S = np.square(S)
    S[S <= 1e-6] = 0
    filtered=np.nonzero(S)[0]
    S = S[filtered]

    results = {}
    if VarCompEst:
        print(U.shape)
        U = U[:,filtered]
        print(U.shape,S.shape)
        var_est=VarComponentEst(S,U,y)
        sigma2_gxg=var_est[1]
        sigma2_e=var_est[2]
        trace=np.sum(S) # compute the trace of phi phi.T
        sumK = np.sum(np.sum(Z,axis=0)**2) # compute the sum(Phi Phi.T)
        print(f'trace is {trace}; sum K is {sumK}')

        cC=trace*1.0/(n*M) - sumK*1.0/(n**2*M)
        print(f'Constant factor is {cC}')
        h2_gxg=cC*sigma2_gxg/(cC*sigma2_gxg+((n-1)*1.0/n)*sigma2_e)
        print(f'Before correction: {sigma2_gxg}; after correction: {h2_gxg}')
        results['varcomp']=var_est
        print(f'Var est is: \n {var_est}')
    t0 = time.time()
    #     S = np.square(SVD[1])
    ts0 = time.time()
    
    # print(f'S raw is {S}')
    
    ts1 = time.time()
    # k = int(np.sum(inner1d(P1,X)))
    t1 = time.time()
    if center:
        # print('calculate centered y')
        # sq_sigma_e0 = (res.T@res)[0]/(n-k)
        sq_sigma_e0 = (y.T @ y - y.T @ X @ P1 @ (X.T @ y))[0] / (n - k)
        # sq_sigma_e0_perm = (yperm.T@yperm - yperm.T@X@P1@(X.T@yperm))[0]/(n-k)
    else:
        sq_sigma_e0 = y.T @ y / n
    # t0 = time.time()
    # print(f'Y is {y}, {np.sum(y)}')
    
    p_value1 = score_test2(sq_sigma_e0, Q, S, center=center)
    p_values2 = score_test_qf(sq_sigma_e0, Q, S, center=center)
    print(f'chi2comb pval: {p_value1} \n FastLMM pval: {p_values2}')
    # print(f'Q is {Q}; sq_sigma_e0 is {sq_sigma_e0}; pval is {p_value1}')
    if Perm:
        p_list = [p_value1]
        for state in range(Perm):
            shuff_idx = np.random.RandomState(seed=state).permutation(n)
            yperm = (y - (X @ (P1 @ (X.T @ y))))[shuff_idx]
            Qperm = np.sum(np.square(yperm.T @ Z))
            sq_sigma_e0_perm = (yperm.T @ yperm)[0] / (n - k)
            p_value1_perm = score_test2(sq_sigma_e0_perm,
                                        Qperm,
                                        S,
                                        center=center)
            p_list.append(p_value1_perm)

        results['pval']=p_list
        return results
    results['pval']=p_value1
    return results


##########
# Update the binary trait process

# def getfullComponentPerm_binary(X, Z, y, center=False,method='Scipy',Perm=10):
#     # X is the covariates that need to be regressed out, res is the residule after regressing out the linear effect
#     # delta is the initial guess of delta value
#     print(f'use {method}')

#     t0 = time.time()
#     n = Z.shape[0]
#     X = np.concatenate((np.ones((n,1)),X),axis=1)
#     y = y.reshape(-1,1)
#     clf = LogisticRegression(random_state=0,fit_intercept=False).fit(X, y)
#     est_mu = clf.predict_proba(X)
#     k = X.shape[1]
#     # yperm = np.random.permutation(y)
#     P1= inverse(X)
#     t1 = time.time()
#     # print(f'inverse P1 takes {t1-t0}')
#     if center:
#         # S = svd(Z.T@Z-(Z.T@P1)@(X.T@Z),compute_uv=False)
#         t0 = time.time()
#         Z = projection(Z,X,P1)
#         # Z = Z - X@P1@(X.T@Z)
#         t1 = time.time()
#         # print(f'Z operation takes {t1-t0}')
#         if method == 'Jax':
#             S = jax_svd(Z)
#         elif method == 'Julia':
#             if Julia_FLAG:
#                 S = FameSVD.fsvd(Z).S
#             else:
#                 S = scipy.linalg.svd(Z,full_matrices = False, compute_uv=False)
#         elif method == 'Scipy':
#             S = scipy_svd(Z)

#         Q = np.sum(np.square(y.T@Z - y.T@X@P1@X.T@Z))

#         t1 = time.time()
#         print(f'svd takes {t1-t0}')
#         t0 = time.time()

#         # Q_perm = np.sum(np.square(yperm.T@Z - yperm.T@X@P1@X.T@Z))
#         t1 = time.time()
#     else:
#         SVD = svd(Z.T@Z)
#         Q = np.sum(np.square(y.T@Z))
#     t0 = time.time()
# #     S = np.square(SVD[1])
#     ts0 = time.time()
#     S = np.square(S)
#     S[S <= 1e-6] = 0
#     S = S[np.nonzero(S)]
#     # S = S[~np.isnan(S)]
#     ts1 = time.time()
#     # k = int(np.sum(inner1d(P1,X)))
#     t1 = time.time()
#     if center:
#         # print('calculate centered y')
#         # sq_sigma_e0 = (res.T@res)[0]/(n-k)
#         sq_sigma_e0 = (y.T@y - y.T@X@P1@(X.T@y))[0]/(n-k)
#         # sq_sigma_e0_perm = (yperm.T@yperm - yperm.T@X@P1@(X.T@yperm))[0]/(n-k)
#     else:
#         sq_sigma_e0 = y.T@y/n
#     # t0 = time.time()
#     p_value1 = score_test2(sq_sigma_e0, Q, S, center=center)
#     if Perm:
#         p_list = [p_value1]
#         for state in range(Perm):
#             shuff_idx = np.random.RandomState(seed=state).permutation(n)
#             yperm = (y-(X@(P1@(X.T@y))))[shuff_idx]
#             Qperm = np.sum(np.square(yperm.T@Z))
#             sq_sigma_e0_perm = (yperm.T@yperm)[0]/(n-k)
#             p_value1_perm = score_test2(sq_sigma_e0_perm, Qperm, S, center=center)
#             p_list.append(p_value1_perm)
#         # t1 = time.time()
#         # print(f'p value test takes {t1-t0}')
#         return p_list

#     return p_value1

# Started on Jun 13th
################


def getRLComponent(X,
                   Z,
                   y,
                   theta=False,
                   dtype='quant',
                   center=False,
                   RL_SKAT=True,
                   method='Julia'):
    # X is the covariates that need to be regressed out, res is the residule after regressing out the linear effect
    # delta is the initial guess of delta value

    t0 = time.time()
    n = Z.shape[0]
    X = np.concatenate((np.ones((n, 1)), X), axis=1)
    k = X.shape[1]
    yperm = np.random.permutation(y)
    P1 = inverse(X)
    t1 = time.time()
    p = X.shape[1]
    if center:
        t0 = time.time()
        Z = projection(Z, X, P1)
        t1 = time.time()
        # print(f'Z operation takes {t1-t0}')
        S = scipy.linalg.svd(X, full_matrices=False, compute_uv=False)
        S = np.square(S)
        S[S <= 1e-6] = 0
        S = S[np.nonzero(S)]
        S = S[~np.isnan(S)]
        sq_sigma_e0 = (y.T @ y - y.T @ X @ P1 @ (X.T @ y)) / (n - p)
        sq_sigma_e0_perm = (yperm.T @ yperm -
                            yperm.T @ X @ P1 @ (X.T @ yperm)) / (n - p)
        t1 = time.time()
        Q = (y.T @ Z) @ (Z.T @ y)
        Q_perm = (yperm.T @ Z) @ (Z.T @ yperm)
        # print("svd takes {}".format(t1-t0))
        Qe = Q / (sq_sigma_e0)
        Qe_perm = Q_perm / (sq_sigma_e0_perm)
        if RL_SKAT:
            # under the assumption that PZ and X has no overlapping
            # C = np.concatenate((Z,X),axis=1)
            t0 = time.time()
            t1 = time.time()
            # print(f'conversion takes {t1-t0}')
            phi = S
            t2 = time.time()
            rankPZ = len(phi)
            rankX = X.shape[1]
            # rankX = np.linalg.matrix_rank(X)
            q = n - rankPZ - rankX
            t1 = time.time()
            k = len(phi)
            S = np.zeros(k + q)
            S[0:k] = phi
            S_perm = S - Qe_perm / (n - p)
            S -= Qe / (n - p)
        else:
            S = S[1]
            S = np.square(SVD[1])
            S[np.abs(S) < 1e-6] = 0
            S = S[np.nonzero(S)]
    else:
        Q = (y.T @ Z) @ (Z.T @ y)
        Qe = Q / (sq_sigma_e0)
        sq_sigma_e0 = y.T @ y / n
        # print('SVD for K')
        SVD = svd(Z, full_matrices=False)
    y = y.reshape(-1, 1)
    # print(f'rank of XinvXT is {p}')
    t0 = time.time()
    if center:
        p_value1 = score_test(S)
        p_value1_perm = score_test(S_perm)
    else:
        p_value1 = score_test(S)
    t1 = time.time()
    # print(f'total p value time is {t1-t0}')
    return [p_value1, p_value1_perm]


def projection_mle(X, P1):
    X = np.array(X, order='F')
    P1 = np.array(P1, order='F')
    P1 = scipy.linalg.blas.sgemm(1., X, P1)
    P1 = scipy.linalg.blas.sgemm(1., P1, X, trans_b=True)
    return P1


def PKP_comp(P, K):
    P = np.array(P, order='F')
    K = np.array(K, order='F')
    t1 = scipy.linalg.blas.sgemm(1., P, K)
    t2 = scipy.linalg.blas.sgemm(1., t1, P)
    return t2


def getmleComponent(X, K, y, center=False):
    # delta is the initial guess of delta value
    t0 = time.time()
    n = K.shape[0]
    y = y.reshape(-1, 1)
    yperm = np.random.permutation(y)
    X = np.concatenate((np.ones((n, 1)), X), axis=1)
    # P1= X@np.linalg.inv(X.T@X)@X.T
    # P = np.eye(n)-P1
    # PKP = P@K@P
    P1 = inverse(X)
    P1 = projection_mle(X, P1)
    P = np.eye(n) - P1
    PKP = PKP_comp(P, K)
    Q = y.T @ PKP @ y
    Q_perm = yperm.T @ PKP @ yperm
    try:
        # S = jax_svd(PKP)
        S = svd(PKP, full_matrices=False, compute_uv=False)
    except:
        print(f'X shape is {X.shape}')
        print(f'P1 shape is {P1.shape}')
        print(f'PKP contains NA: {np.isnan(np.sum(PKP))}')
        return []
    t1 = time.time()
    print("svd takes {}".format(t1 - t0))
    S = S[S >= 1e-6]
    S = S[np.nonzero(S)]
    t0 = time.time()
    k = X.shape[1]
    t1 = time.time()

    if center:
        sq_sigma_e0 = (y.T @ y - (y.T @ P1 @ y))[0] / (n - k)
        sq_sigma_e0_perm = (yperm.T @ yperm -
                            (yperm.T @ P1 @ yperm))[0] / (n - k)
    else:
        sq_sigma_e0 = y.T @ y / n
    t0 = time.time()
    if center:
        p_value1 = score_test2(sq_sigma_e0,
                               Q,
                               S,
                               center=center,
                               decompose=False)
        p_value_perm = score_test2(sq_sigma_e0_perm,
                                   Q_perm,
                                   S,
                                   center=center,
                                   decompose=False)
    else:
        p_value1 = score_test2(sq_sigma_e0,
                               Q,
                               S,
                               center=center,
                               decompose=False)
    t1 = time.time()
    print(f'p value is {p_value1}')
    return [p_value1, p_value_perm]


if __name__ == "__main__":
    results = []
    dtype = 'quant'
    np.random.seed(1)
    from sklearn import preprocessing
    from sklearn.kernel_approximation import PolynomialCountSketch
    print(f'Simulating linear effect with h2 = 0.5')
    for sigma1sq, sigma2sq in [(0.01, 0.99)]:
        N = 5000
        M = 10
        D = M * 50
        gamma = 0.1
        X = np.random.binomial(2, np.random.uniform(0.3, 0.7, M), (N, M))
        

        mapping = PolynomialFeatures((2, 2),interaction_only=True,include_bias=False)
        for i in range(200):
            Z = mapping.fit_transform(X)
            Z = preprocessing.scale(Z)
            print(f'Z shape is {Z.shape}')
            eps = np.random.randn(N) * np.sqrt(sigma2sq)
            beta = np.random.randn(Z.shape[1]) * np.sqrt(sigma1sq)*1.0
            y = Z.dot(beta) + eps
            # plist = getfullComponent(X,
            #                          Z,
            #                          y,
            #                          dtype=dtype,
            #                          center=True,
            #                          method="Julia")
            # print(f'FastKAST p value is {plist[0][0]}')
            results = getfullComponentPerm(None,Z,y.reshape(1,-1),VarCompEst=True)
            # print(results)
            # results.append((plist, sigma1sq / (sigma1sq + sigma2sq), N, M, D))

    # dump(results, f'./test.pkl')
