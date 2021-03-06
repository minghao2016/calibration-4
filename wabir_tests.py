"""
Tests for BBQ, IR, BIR, ENIR, and WABIR
Metrics: AUC-ROC, MSE, ECE
Misc: BBQ estimates rather low probabilities for samples with highest scores. WABIR totally
produces better probabilities for these. Use some metric to only compare these.
"""

import datetime
import isotonic
import numpy as np
from oct2py import octave
from sklearn.isotonic import IsotonicRegression
# ENIR-code is R:
import rpy2.robjects as robjects
from rpy2.robjects.packages import importr
enir = importr('enir')
r = robjects.r
# Automatic conversion or numpy arrays to R-vectors
import rpy2.robjects.numpy2ri
rpy2.robjects.numpy2ri.activate()
# from sklearn.metrics import roc_auc_score
# Enable octave to find Naeini's functions!
# (download from https://github.com/pakdaman/calibration)
octave.eval("addpath('./calibration/BBQ/')", verbose=False)

# Set test parameters:
dataset = int(input("Select dataset to run experiment on (1, 2, or 3): "))
n_iterations = int(input("Set number of iterations (30 used in paper): "))

# Load dataset:
if dataset == 1:
    # Read data for test 1:
    test_description = "test1"
    data_class = isotonic.load_pickle("./data/dataset_1_class.pickle")
    data_scores = isotonic.load_pickle("./data/dataset_1_scores.pickle")
elif dataset == 2:
    # Read data for test 2:
    test_description = "test2"
    data_class = isotonic.load_pickle("./data/dataset_2_class.pickle")
    data_scores = isotonic.load_pickle("./data/dataset_2_scores.pickle")
elif dataset == 3:
    test_description = "test3"
    data_class = isotonic.load_pickle("./data/dataset_3_class.pickle")
    data_scores = isotonic.load_pickle("./data/dataset_3_scores.pickle")
elif dataset == 4:  # Hidden experiment. Does not really provide anything interesting.
    test_description = "test4"
    data_class = np.random.binomial(1, .5, 30000)
    data_scores = np.random.uniform(low=0, high=1, size=30000)
elif dataset == 5:  # Test mode
    tmp_class = isotonic.load_pickle("./data/dataset_1_class.pickle")
    tmp_scores = isotonic.load_pickle("./data/dataset_1_scores.pickle")
    test_description = "test1"
    data_class = tmp_class[:1000]
    data_scores = tmp_scores[:1000]

else:
    print("Not a valid dataset selection.")
    import sys
    sys.exit()
print("Dataset with " + str(data_class.shape[0]) + " samples loaded.")

k = 100
print("Expected calibration error (ECE) and MCE calculated with k = " + str(k))

# Set minimum and maximum values for predictions (where applicable)
y_min = 1e-3
y_max = 1 - 1e-3

ir_metrics = []
bir_metrics = []
wabir_metrics = []
bbq_metrics = []
enir_metrics = []
rcir_d20_metrics = []
rcir_d10_metrics = []
rcir_d05_metrics = []
rcir_d30_metrics = []
rcir_d40_metrics = []

# Prepare for @-metrics
levels = [.95, .96, .97, .98, .99]
k_levels = [5, 4, 3, 2, 1]  # Corresponds to k==100 for complete dataset
at_metrics = {'bbq': [], 'ir': [], 'enir': [], 'wabir': [], 'bir': [],
              'rcir20': [], 'rcir10': [], 'rcir05': [], 'rcir30': [], 'rcir40': []}

# ir_high_scoring = []
# bir_high_scoring = []
# wabir_high_scoring = []
# enir_high_scoring = []

for i in range(n_iterations):
    print("Iteration {0} of {1}".format(i, n_iterations))
    print(datetime.datetime.now())
    # Shuffle samples:
    # This is super important as the data is generated by a non-stationary process!
    # Data preparation includes shuffling (to randomize between multiple runs),
    # and splitting up in training- and testing sets.
    n_rows = data_scores.shape[0]
    idx = np.random.permutation(range(n_rows))
    data_class = data_class[idx]
    data_scores = data_scores[idx]
    test_class = data_class[:n_rows * 1 // 3]
    test_scores = data_scores[:n_rows * 1 // 3]
    training_class = data_class[n_rows * 1 // 3:]
    training_scores = data_scores[n_rows * 1 // 3:]

    # Create BBQ-model
    octave.push('training_scores', training_scores, verbose=False)
    octave.push('training_class', training_class, verbose=False)
    octave.eval('options.N0 = 2', verbose=False)
    octave.eval("bbq_model = build(training_scores', training_class', options)", verbose=False)
    octave.push('test_scores', test_scores)
    octave.eval("test_prob = predict(bbq_model, test_scores, 1)", verbose=False)
    bbq_prob = octave.pull('test_prob', verbose=False)
    bbq_prob = np.array([item[0] for item in bbq_prob])
    bbq_metrics.append(isotonic.get_metrics(test_class, bbq_prob, k=k))
    # Create isotonic regression model
    ir_model = IsotonicRegression(y_min=y_min, y_max=y_max, out_of_bounds='clip')
    ir_model.fit(X=training_scores, y=training_class)
    ir_prob = isotonic.predict(ir_model, test_scores)
    ir_metrics.append(isotonic.get_metrics(test_class, ir_prob, k=k))
    # Create ENIR model using R:
    enir_model = enir.enir_build(robjects.FloatVector(training_scores.tolist()),
                                 robjects.BoolVector(training_class.tolist()))
    enir_prob = enir.enir_predict(enir_model, robjects.FloatVector(test_scores.tolist()))
    # Convert to numpy.array:
    enir_prob = np.array(enir_prob)
    enir_metrics.append(isotonic.get_metrics(test_class, enir_prob, k=k))

    # Create weighted (by likelihood) averaged bootstrapped isotonic regression.
    # I am using the identical IR models for BIR, which is basically also an
    # ensemble model but where all models have equal weight.
    wabir_model = isotonic.train_wabir(training_class, training_scores)
    wabir_prob = isotonic.predict_wabir(wabir_model, test_scores)
    wabir_metrics.append(isotonic.get_metrics(test_class, wabir_prob, k=k))
    # Estimating bir-probabilities using the same IR models as generated by wabir:
    bir_prob = isotonic.predict_wabir(wabir_model, test_scores, weighted_average=False)
    bir_metrics.append(isotonic.get_metrics(test_class, bir_prob, k=k))
    # Separate the top-N% best scoring test samples (currently 100%, i.e. all):
    # Skip top-10% comparison and replace with just 'top' where samples with higher
    # probabilities than max(bbq_prob)?
    # top_idx = np.argsort(test_scores)  # Top-10 idx by score or probabilities? E.g. BBQ.
    # top_ten_idx = top_idx[int(len(top_idx) * .9):]  # NOT USED ANYWHERE!

    rcir_d20_model = isotonic.train_rcir(training_class, training_scores, d=.2)
    rcir_d20_prob = isotonic.predict_rcir(rcir_d20_model, test_scores)
    rcir_d10_model = isotonic.train_rcir(training_class, training_scores, d=.1)
    rcir_d10_prob = isotonic.predict_rcir(rcir_d10_model, test_scores)
    rcir_d05_model = isotonic.train_rcir(training_class, training_scores, d=.05)
    rcir_d05_prob = isotonic.predict_rcir(rcir_d05_model, test_scores)
    rcir_d30_model = isotonic.train_rcir(training_class, training_scores, d=.3)
    rcir_d30_prob = isotonic.predict_rcir(rcir_d30_model, test_scores)
    rcir_d40_model = isotonic.train_rcir(training_class, training_scores, d=.4)
    rcir_d40_prob = isotonic.predict_rcir(rcir_d40_model, test_scores)

    rcir_d20_metrics.append(isotonic.get_metrics(test_class, rcir_d20_prob, k=k))
    rcir_d10_metrics.append(isotonic.get_metrics(test_class, rcir_d10_prob, k=k))
    rcir_d05_metrics.append(isotonic.get_metrics(test_class, rcir_d05_prob, k=k))
    rcir_d30_metrics.append(isotonic.get_metrics(test_class, rcir_d30_prob, k=k))
    rcir_d40_metrics.append(isotonic.get_metrics(test_class, rcir_d40_prob, k=k))

    # # Metrics for all datapoints with probability higher than max(bbq_prob) (other methods).
    # ir_high_scoring.append(isotonic.metrics_for_high_scoring_samples(test_class, bbq_prob, ir_prob))
    # bir_high_scoring.append(isotonic.metrics_for_high_scoring_samples(test_class, bbq_prob, bir_prob))
    # wabir_high_scoring.append(isotonic.metrics_for_high_scoring_samples(test_class, bbq_prob, wabir_prob))
    # enir_high_scoring.append(isotonic.metrics_for_high_scoring_samples(test_class, bbq_prob, enir_prob))

    # @-metrics
    probabilities = {'bbq': bbq_prob, 'ir': ir_prob, 'enir': enir_prob, 'wabir': wabir_prob, 'bir': bir_prob,
                     'rcir20': rcir_d20_prob, 'rcir10': rcir_d10_prob, 'rcir05': rcir_d05_prob,
                     'rcir30': rcir_d30_prob, 'rcir40': rcir_d40_prob}
    for level, k_level in zip(levels, k_levels):
        for key in probabilities.keys():
            at_metrics[key].append(isotonic.metrics_at(test_class, probabilities[key], test_scores, low=level, k=k_level))

# Overall metrics
print("Overall metrics")
print("\tMSE \t\tAUC-ROC \tECE \t\tmax(p)")
ir = isotonic.average_metrics(ir_metrics)  # Average IR metrics
print("IR \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(ir[0], ir[1], ir[2], ir[3]))
bir = isotonic.average_metrics(bir_metrics)  # Average BIR metrics
print("BIR \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(bir[0], bir[1], bir[2], bir[3]))
wabir = isotonic.average_metrics(wabir_metrics)  # Average WABIR metrics
print("WABIR \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(wabir[0], wabir[1], wabir[2], wabir[3]))
tmp = isotonic.average_metrics(rcir_d40_metrics)  # Average RCIR metrics
print("RCIR40 \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(tmp[0], tmp[1], tmp[2], tmp[3]))
tmp = isotonic.average_metrics(rcir_d30_metrics)  # Average RCIR metrics
print("RCIR30 \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(tmp[0], tmp[1], tmp[2], tmp[3]))
tmp = isotonic.average_metrics(rcir_d20_metrics)  # Average RCIR metrics
print("RCIR20 \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(tmp[0], tmp[1], tmp[2], tmp[3]))
tmp = isotonic.average_metrics(rcir_d10_metrics)  # Average RCIR metrics
print("RCIR10 \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(tmp[0], tmp[1], tmp[2], tmp[3]))
tmp = isotonic.average_metrics(rcir_d05_metrics)  # Average RCIR metrics
print("RCIR05 \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(tmp[0], tmp[1], tmp[2], tmp[3]))
bbq = isotonic.average_metrics(bbq_metrics)  # Average BBQ metrics
print("BBQ \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(bbq[0], bbq[1], bbq[2], bbq[3]))
enir_tmp = isotonic.average_metrics(enir_metrics)  # Average IR metrics
print("ENIR \t{0:.7} \t{1:.7} \t{2:.7} \t{3:.7}".format(enir_tmp[0], enir_tmp[1], enir_tmp[2], enir_tmp[3]))

# print("\nMetrics for samples with higher probabilities than max(bbq)")
# print("\tSamples \tEmpiric frequency \tEstimate \tBBQ-estimate")
# ir_high = isotonic.average_high_scoring(ir_high_scoring)
# print("IR \t{0:.7} \t\t{1:.7} \t\t{2:.7} \t{3:.7}".format(ir_high[0], ir_high[1], ir_high[2], ir_high[3]))
# bir_high = isotonic.average_high_scoring(bir_high_scoring)
# print("BIR \t{0:.7} \t\t{1:.7} \t\t{2:.7} \t{3:.7}".format(bir_high[0], bir_high[1], bir_high[2], bir_high[3]))
# wabir_high = isotonic.average_high_scoring(wabir_high_scoring)
# print("WABIR \t{0:.7} \t\t{1:.7} \t\t{2:.7} \t{3:.7}".format(wabir_high[0], wabir_high[1], wabir_high[2], wabir_high[3]))
# enir_high = isotonic.average_high_scoring(enir_high_scoring)
# print("ENIR \t{0:.7} \t\t{1:.7} \t\t{2:.7} \t{3:.7}".format(enir_high[0], enir_high[1], enir_high[2], enir_high[3]))


# Print @-metrics ## AVERAGING NOT DONE YET!
for level in levels:
    isotonic.print_at_metrics(at_metrics, level)


"""
Counting the number of times one method is better than another is equivalent to a Monte-Carlo
simulation of the rank-sum test, which is equivalent to Mann-Whitney U and AUC-ROC.
We could hypothetically use BBQ for all other samples except for the ones that are mapped to
higher probabilities by other methods (pick any!), and replace those higher probabilities with
one single bin characterized by a beta-distribution and the positive and negative samples
that fell within that bin during training time. By such an approach, we see that the probability
of these samples having a probability as small as the one suggested by BBQ is vanishingly small.
"""
