"""Models used for the training set sampling pipeline."""

from typing import cast

import numpy as np
import pandas as pd
from pydantic import Field
from scythe.base import ExperimentInputSpec

from globi.models.surrogate.configs.pipeline import StageSpec
from globi.models.surrogate.samplers import Priors


class SampleSpec(StageSpec):
    """A spec for the sampling stage of the progressive training."""

    # TODO: add the ability to receive the last set of error metrics and use them to inform the sampling
    priors: Priors = Field(
        ...,
        description="The priors to use for sampling.",
    )

    def stratified_selection(self) -> pd.DataFrame | None:
        """Sample the gis data."""
        df = self.parent.context_data
        if df is None:
            return None

        stratification_field = self.parent.stratification.field
        stratification_aliases = self.parent.stratification.aliases

        if stratification_field not in df.columns and not any(
            alias in df.columns for alias in stratification_aliases
        ):
            msg = f"Stratification field {stratification_field} not found in gis data.  Please check the field name and/or the aliases."
            raise ValueError(msg)

        if stratification_field not in df.columns:
            stratification_field = next(
                alias for alias in stratification_aliases if alias in df.columns
            )

        strata = cast(list[str], df[stratification_field].unique().tolist())

        if self.parent.stratification.sampling == "equal":
            return self.sample_equally_by_stratum(df, strata, stratification_field)
        elif self.parent.stratification.sampling == "error-weighted":
            msg = "Error-weighted sampling is not yet implemented."
            raise NotImplementedError(msg)
        elif self.parent.stratification.sampling == "proportional":
            msg = "Proportional sampling is not yet implemented."
            raise NotImplementedError(msg)
        else:
            msg = f"Invalid sampling method: {self.parent.stratification.sampling}"
            raise ValueError(msg)

    def sample_equally_by_stratum(
        self, df: pd.DataFrame, strata: list[str], stratification_field: str
    ) -> pd.DataFrame:
        """Sample equally by stratum.

        This will break the dataframe up into n strata and ensure that each strata ends up with the same number of samples.

        Args:
            df (pd.DataFrame): The dataframe to sample from.
            strata (list[str]): The unique values of the strata.
            stratification_field (str): The field to stratify the data by.

        Returns:
            samples (pd.DataFrame): The sampled dataframe.
        """
        stratum_dfs = {
            stratum: df[df[stratification_field] == stratum] for stratum in strata
        }
        n_per_iter = self.parent.iteration.n_per_gen_for_current_iter
        n_per_stratum = max(
            n_per_iter // len(strata),
            (
                self.parent.iteration.min_per_stratum
                if self.parent.iteration.current_iter == 0
                else 0
            ),
        )

        # TODO: consider how we want to handle potentially having the same geometry appear in both
        # the training and testing sets.
        # if any(len(stratum_df) < n_per_stratum for stratum_df in stratum_dfs.values()):
        #     msg = "There are not enough buildings in some strata to sample the desired number of buildings per stratum."
        #     # connsider making this a warning?
        #     raise ValueError(msg)

        sampled_strata = {
            stratum: stratum_df.sample(
                n=n_per_stratum, random_state=self.random_generator, replace=True
            )
            for stratum, stratum_df in stratum_dfs.items()
        }
        return cast(pd.DataFrame, pd.concat(sampled_strata.values()))

    # TODO: Add the ability to check the compatiblity of a sampling spec with an input_validator_type.

    def populate_sample_df(self) -> pd.DataFrame:
        """Populate the sample dataframe with the priors."""
        base_df = self.stratified_selection()
        if base_df is None:
            base_df = pd.DataFrame()
        # in case we needed more samples due to the strata min req
        n_samples = max(self.parent.iteration.n_per_gen_for_current_iter, len(base_df))
        return self.priors.sample(
            base_df,
            n_samples,
            self.random_generator,
        )

    def convert_to_specs(
        self, df: pd.DataFrame, input_validator: type[ExperimentInputSpec]
    ):
        """Convert the sampled dataframe to a list of simulation specs."""
        df["experiment_id"] = "placeholder"
        df["sort_index"] = np.arange(len(df))
        return [
            input_validator.model_validate(row) for row in df.to_dict(orient="records")
        ]
