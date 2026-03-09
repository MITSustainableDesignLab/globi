"""Models used for the training set sampling pipeline."""

from typing import cast

import pandas as pd

from globi.models.surrogate.configs.pipeline import StageSpec


class SampleSpec(StageSpec):
    """A spec for the sampling stage of the progressive training."""

    # TODO: add the ability to receive the last set of error metrics and use them to inform the sampling

    def stratified_selection(self) -> pd.DataFrame:
        """Sample the gis data."""
        df = self.parent.gis_data

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

    # def sample_semantic_fields(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Sample the semantic fields."""
    #     # TODO: consider randomizing the locations?
    #     semantic_fields = self.progressive_training_spec.semantic_fields_data
    #     for field in semantic_fields.Fields:
    #         if isinstance(field, CategoricalFieldSpec):
    #             options = field.Options
    #             df[field.Name] = self.random_generator.choice(options, size=len(df))
    #         elif isinstance(field, NumericFieldSpec):
    #             df[field.Name] = self.random_generator.uniform(
    #                 field.Min, field.Max, size=len(df)
    #             )
    #         else:
    #             msg = f"Invalid field type: {type(field)}"
    #             raise TypeError(msg)
    #     return df

    # def sample_basements_and_attics(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Add basement/attics to models."""
    #     # get the options for the type literal
    #     options: list[BasementAtticOccupationConditioningStatus] = [
    #         "none",
    #         "occupied_unconditioned",
    #         "unoccupied_unconditioned",
    #         "occupied_conditioned",
    #         "unoccupied_conditioned",
    #     ]
    #     weights = [0.5, *([0.5 / 4] * 4)]
    #     # sample the type literal
    #     df["basement"] = self.random_generator.choice(options, size=len(df), p=weights)
    #     df["attic"] = self.random_generator.choice(options, size=len(df), p=weights)
    #     df["exposed_basement_frac"] = self.random_generator.uniform(
    #         0.1, 0.5, size=len(df)
    #     )
    #     return df

    # def sample_wwrs(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Sample the wwrs."""
    #     wwr_min = 0.05
    #     wwr_max = 0.35
    #     df["wwr"] = self.random_generator.uniform(wwr_min, wwr_max, size=len(df))
    #     return df

    # def sample_f2f_heights(self, df: pd.DataFrame) -> pd.DataFrame:
    #     """Sample the f2f heights."""
    #     f2f_min = 2.3
    #     f2f_max = 4.3
    #     df["f2f_height"] = self.random_generator.uniform(f2f_min, f2f_max, size=len(df))
    #     return df

    def to_sim_specs(self, df: pd.DataFrame):
        """Convert the sampled dataframe to a list of simulation specs.

        For now, we are assuming that all the other necessary fields are present and we are just
        ensuring that sort_index and experiment_id are set appropriately.
        """
        # df["semantic_field_context"] = df.apply(
        #     lambda row: {
        #         field.Name: row[field.Name]
        #         for field in self.progressive_training_spec.semantic_fields_data.Fields
        #     },
        #     axis=1,
        # )
        # df["sort_index"] = np.arange(len(df))
        # df["experiment_id"] = self.experiment_key
        # # TODO: consider allowing the component map/semantic_fields/database to be inherited from the row
        # # e.g. to allow multiple component maps and dbs per run.
        # df["component_map_uri"] = str(self.progressive_training_spec.component_map_uri)
        # df["semantic_fields_uri"] = str(
        #     self.progressive_training_spec.semantic_fields_uri
        # )
        # df["db_uri"] = str(self.progressive_training_spec.database_uri)
        return df

    # def make_payload(self, s3_client: S3ClientType):
    #     """Make the payload for the scatter gather task, including generating the simulation specs and serializing them to s3."""
    #     df = self.stratified_selection()
    #     # df = self.sample_semantic_fields(df)
    #     # df = self.sample_basements_and_attics(df)
    #     # df = self.sample_wwrs(df)
    #     # df = self.sample_f2f_heights(df)
    #     df = self.to_sim_specs(df)
    #     # serialize to a parquet file and upload to s3
    #     bucket = self.progressive_training_spec.storage_settings.BUCKET
    #     with tempfile.TemporaryDirectory() as tmpdir:
    #         tmpdir = Path(tmpdir)
    #         fpath = tmpdir / "specs.pq"
    #         df.to_parquet(fpath)
    #         key = f"hatchet/{self.experiment_key}/specs.pq"
    #         specs_uri = f"s3://{bucket}/{key}"
    #         s3_client.upload_file(fpath.as_posix(), bucket, key)

    #     payload = {
    #         "specs": specs_uri,
    #         "bucket": bucket,
    #         "workflow_name": "simulate_sbem_shoebox",
    #         "experiment_id": self.experiment_key,
    #         "recursion_map": {
    #             "factor": self.progressive_training_spec.iteration.recursion_factor,
    #             "max_depth": self.progressive_training_spec.iteration.recursion_max_depth,
    #         },
    #     }
    #     return payload
