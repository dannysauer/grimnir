# ADR: Share one versioned feature extractor between training and inference

## Record

| Field | Value |
| --- | --- |
| Date | 2026-04-18 |
| Status | Accepted |
| Owner | Danny Sauer |
| Author | Danny Sauer |
| Scope | Where CSI feature extraction lives and how a model declares the features it was trained on. Excludes which features are extracted. |
| Related | Commit `404b199`; [#16](https://github.com/dannysauer/grimnir/issues/16); [ML pipeline](../architecture/ml-pipeline.md) |
| Implementation | `mimir/src/csi_models/features.py`, `nornir/src/nornir/train.py`, `volva/src/volva/model_loader.py` |

## Business driver

A model is only as good as the match between the features it was trained on
and the features it sees live. If Nornir and Völva each computed features
their own way, a small difference would produce confident, wrong room
predictions with no error anywhere.

## Constraints

- Training and inference are separate services with separate release cycles
  ([2026-04-18](2026-04-18-ml-services-use-freki-api.md)).
- Geri imports the same shared package and shouldn't have to install numpy.

## Decision

**Y statement:** We will keep feature extraction in one module,
`csi_models.features`, that both Nornir and Völva import, and stamp every
model with a `feature_config` that carries a version, because drift between
training and serving features fails silently, so Völva can refuse a model it
can't serve correctly.

The module sits behind the `[features]` extra of `csi-models` and isn't
re-exported from the package root, which keeps numpy out of Geri.

- Nornir and Völva MUST compute features with
  `csi_models.features.extract_features`.
- A change that alters extractor output MUST increment `FEATURE_VERSION`.
- Völva MUST refuse a model whose `feature_config.version` differs from its
  own `FEATURE_VERSION`.
- Every parameter that changes feature values MUST be part of
  `feature_config`, so it travels with the model.

## Consequences

- Shipping a new extractor means retraining: models from the old version stop
  loading.
- The last rule isn't met yet. Window size changes feature values but lives
  in Nornir's job spec and Völva's `WINDOW_SIZE` variable, not in
  `feature_config` ([#61](https://github.com/dannysauer/grimnir/issues/61)).
- One integer version can't describe a family of extractors. A pipeline that
  grows filtering, phase sanitization, or spectral features will need
  `feature_config` to say which steps ran.

## Alternatives considered

### Let each service compute its own features

This is what two independent services would do by default. Commit `404b199`
names the cost: "drift between the two produces silently-wrong predictions."

### Bundle the extractor into the model artifact

Not recorded as considered. A scikit-learn `Pipeline` could carry its own
preprocessing, which removes the version check but makes the pickle the only
definition of the features and widens what an uploaded model can execute.
